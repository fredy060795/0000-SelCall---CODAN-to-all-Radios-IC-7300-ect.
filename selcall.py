"""SelCall Terminal - CODAN / CCIR 493-4, ZVEI, CCIR, DTMF, Necode.

Connection to the radio set up like in HFChat:

  Funkgerät  -> radio model (CODAN NGT, IC-7300 ...; radios.txt adds more)
  Modem/PTC  -> COM port, baud rate, modem type of the PACTOR modem
  CAT/RIG    -> COM port, baud rate, CI-V address, protocol of the radio
  TNC/PTT    -> PTT method CAT / TNC / RTS / DTR / VOX

CODAN radio: the radio sends its own Codan selcall, the program gives the
CICS command ("selcall 435299") directly (CAT) or through the modem (TNC,
"TRX T selcall 435299").  Other radios: the PC makes the CCIR 493-4 FSK and
keys the radio by CAT/RTS/DTR.
"""

import io
import json
import os
import queue
import re
import threading
import time
import wave

import numpy as np
import tkinter as tk
from tkinter import messagebox, ttk

try:
    import sounddevice as sd
except Exception:  # pragma: no cover
    sd = None

import autodetect
import radio_models
from radio_link import (CAT_PROTOCOLS, PTC_BAUD_RATES, PTC_MODEM_TYPES, PTT_METHODS, RIG_BAUD_RATES,
                        CODAN_CALLS, RadioLink, list_serial_ports)
from selcall_codec import NECODE_TONES, TONE_STANDARDS, AudioGenerator, CCIR493Decoder, CodanSelcallEncoder

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")

DEFAULT_CONFIG = {
    "RADIO_MODEL": "",
    "PTC_SERIAL_PORT": "",
    "PTC_BAUD": 57600,
    "PTC_MODEM_TYPE": "AUTO",
    "RIG_SERIAL_PORT": "",
    "RIG_BAUD": 115200,
    "CAT_ADDRESS": "94",
    "CAT_PROTOCOL": "ICOM",
    "PTT_METHOD": "CAT",
    "PTT_DELAY_MS": 300,
    "AUDIO_IN": "",
    "AUDIO_OUT": "",
    "OUR_ID": "",
    "CODAN_MODE": "AUTO",            # AUTO: Codan -> CICS, others -> audio | CICS | AUDIO
    **{key: default for key, default, _name in CODAN_CALLS.values()},
    "CODAN_SEND_SELF_ID": False,
    "CODAN_PREAMBLE_S": 2.0,
    "AUTO_CONNECT": True,
}

# settings.json of the old version (lower case keys)
_OLD_KEYS = {
    "port": "RIG_SERIAL_PORT", "baud": "RIG_BAUD", "our_id": "OUR_ID",
    "civ_address": "CAT_ADDRESS", "codan_preamble": "CODAN_PREAMBLE_S",
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return cfg
    for old, new in _OLD_KEYS.items():
        if old in data and new not in data:
            data[new] = data[old]
    if "audio_out_name" in data and "AUDIO_OUT" not in data:
        data["AUDIO_OUT"] = data["audio_out_name"]
    if "audio_in_name" in data and "AUDIO_IN" not in data:
        data["AUDIO_IN"] = data["audio_in_name"]
    old_ptt = str(data.get("ptt_mode", ""))
    if old_ptt and "PTT_METHOD" not in data:
        if "Icom" in old_ptt:
            data["PTT_METHOD"], data["CAT_PROTOCOL"] = "CAT", "ICOM"
        elif "Yaesu" in old_ptt:
            data["PTT_METHOD"], data["CAT_PROTOCOL"] = "CAT", "Yaesu"
        elif "Codan Envoy" in old_ptt:
            data["PTT_METHOD"], data["CAT_PROTOCOL"] = "CAT", "CODAN"
        elif "Pactor Modem Command" in old_ptt:
            data["PTT_METHOD"] = "TNC"
        else:
            data["PTT_METHOD"] = "RTS"
    for key in DEFAULT_CONFIG:
        if key in data:
            cfg[key] = data[key]
    return cfg


def save_config(cfg: dict):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as handle:
        json.dump({k: cfg.get(k, v) for k, v in DEFAULT_CONFIG.items()}, handle, indent=4, ensure_ascii=False)


def _host_api_order():
    """MME first: it exists on every Windows PC, converts the sample rate itself
    and shows every device once (DirectSound/WASAPI/WDM-KS list them again)."""
    try:
        apis = sd.query_hostapis()
    except Exception:
        return []
    names = [str(api.get("name", "")) for api in apis]
    order = [i for i, n in enumerate(names) if n == "MME"]
    order += [i for i, n in enumerate(names) if n != "MME"]
    return order


def _devices(kind: str):
    """[(index, name)] of one host API (MME on Windows) for 'in' or 'out'."""
    if sd is None:
        return []
    key = "max_input_channels" if kind == "in" else "max_output_channels"
    try:
        devices = sd.query_devices()
    except Exception:
        return []
    order = _host_api_order()
    for api in order[:1] or [None]:
        result = []
        for i, dev in enumerate(devices):
            if dev[key] > 0 and (api is None or dev["hostapi"] == api):
                # "Microsoft Sound Mapper" / "Primärer Soundtreiber" = the Windows
                # default device (the PC speakers) - never a radio
                if re.search(r"mapper|primär|primary", dev["name"], re.IGNORECASE):
                    continue
                if dev["name"] not in [n for _, n in result]:
                    result.append((i, dev["name"]))
        if result:
            return result
    return []


def audio_devices(kind: str) -> list:
    """Names of input ('in') or output ('out') devices, each sound card once."""
    return [name for _, name in _devices(kind)]


def audio_device_index(name: str, kind: str):
    if sd is None or not name:
        return None
    for i, dev_name in _devices(kind):
        if dev_name == name:
            return i
    key = "max_input_channels" if kind == "in" else "max_output_channels"
    try:  # saved from another host API
        for i, dev in enumerate(sd.query_devices()):
            if dev["name"] == name and dev[key] > 0:
                return i
    except Exception:
        pass
    return None


class AudioDecoderEngine:
    """Very simple decoder for sequential tone selcall (ZVEI, CCIR ...)."""

    def __init__(self, app_callback, sample_rate=48000, block_size=2048):
        self.app_callback = app_callback
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.stream = None
        self.is_running = False
        self.last_char = None
        self.last_time = 0
        self.ccir493 = CCIR493Decoder(sample_rate)
        self.blocks = queue.Queue(maxsize=400)
        threading.Thread(target=self._ccir493_worker, daemon=True).start()

    def _ccir493_worker(self):
        while True:
            block = self.blocks.get()
            try:
                for call in self.ccir493.feed(block):
                    self.app_callback("call", call)
            except Exception:
                pass

    def start(self, device_id):
        self.stop()
        if sd is None:
            return False
        try:
            self.stream = sd.InputStream(device=device_id, channels=1, samplerate=self.sample_rate,
                                         blocksize=self.block_size, callback=self._audio_callback)
            self.stream.start()
            self.is_running = True
            return True
        except Exception:
            self.is_running = False
            return False

    def stop(self):
        self.is_running = False
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

    def _audio_callback(self, indata, frames, time_info, status):
        if not self.is_running:
            return
        signal_data = indata[:, 0]
        rms = float(np.sqrt(np.mean(signal_data ** 2)))
        self.app_callback("level", rms)
        try:
            self.blocks.put_nowait(signal_data.copy())   # CODAN decoder runs in its own thread
        except queue.Full:
            pass
        if rms < 0.02:
            return
        fft_data = np.abs(np.fft.rfft(signal_data * np.hanning(len(signal_data))))
        freqs = np.fft.rfftfreq(len(signal_data), 1.0 / self.sample_rate)
        peak_freq = float(freqs[int(np.argmax(fft_data))])
        current_mode = self.app_callback("get_mode", None)
        mode_cfg = TONE_STANDARDS.get(current_mode, {})
        detected_char = None
        if mode_cfg.get("type") == "sequential":
            for char, freq in mode_cfg.get("tones", {}).items():
                if abs(peak_freq - freq) < 25:
                    detected_char = char
                    break
        if detected_char:
            now = time.time()
            if detected_char != self.last_char or (now - self.last_time) > 0.15:
                self.last_char = detected_char
                self.last_time = now
                self.app_callback("char", (current_mode, detected_char, rms))


# =============================================================================
# Settings (layout like HFChat: Funkgerät, Modem / PTC, CAT / RIG, TNC / PTT)
# =============================================================================
class SettingsDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Einstellungen")
        self.resizable(True, True)
        self.transient(app)
        cfg = app.cfg

        # Save / Cancel always visible at the bottom, the rest scrolls
        bottom = ttk.Frame(self, padding=(8, 6))
        bottom.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Button(bottom, text="Speichern", command=self._save).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bottom, text="Abbrechen", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Separator(self).pack(side=tk.BOTTOM, fill=tk.X)

        holder = ttk.Frame(self)
        holder.pack(fill=tk.BOTH, expand=True)
        self._canvas = tk.Canvas(holder, highlightthickness=0, borderwidth=0)
        bar = ttk.Scrollbar(holder, orient=tk.VERTICAL, command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=bar.set)
        bar.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        outer = ttk.Frame(self._canvas, padding=8)
        self._outer_id = self._canvas.create_window((0, 0), window=outer, anchor=tk.NW)
        outer.bind("<Configure>", lambda _e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", lambda e: self._canvas.itemconfigure(self._outer_id, width=e.width))
        self.bind("<MouseWheel>", self._on_wheel)                      # Windows / macOS
        self.bind("<Button-4>", lambda _e: self._canvas.yview_scroll(-3, "units"))   # Linux
        self.bind("<Button-5>", lambda _e: self._canvas.yview_scroll(3, "units"))
        height = max(400, min(860, self.winfo_screenheight() - 120))
        self.geometry(f"640x{height}")

        f_auto = ttk.Frame(outer)
        f_auto.pack(fill=tk.X, pady=(0, 4))
        self.btn_auto = ttk.Button(f_auto, text="🔍 Automatisch erkennen", command=self._auto_detect)
        self.btn_auto.pack(side=tk.LEFT)
        self.lbl_auto = ttk.Label(f_auto, text="Funkgerät wählen, dann hier klicken: sucht COM Ports, Baudrate "
                                               "und Soundkarte", foreground="gray", wraplength=380)
        self.lbl_auto.pack(side=tk.LEFT, padx=8)

        # --- Funkgerät ---------------------------------------------------
        f_radio = ttk.LabelFrame(outer, text="Funkgerät", padding=8)
        f_radio.pack(fill=tk.X, pady=4)
        names = ["(manuell)"]
        for _group, members in radio_models.grouped_names(app.profiles):
            names += members
        self.cb_radio = self._combo(f_radio, 0, "Funkgerät:", names, cfg.get("RADIO_MODEL") or "(manuell)", width=28)
        self.cb_radio.bind("<<ComboboxSelected>>", lambda _e: self._apply_radio_model())
        self.lbl_profile = ttk.Label(f_radio, text="", foreground="gray")
        self.lbl_profile.grid(row=1, column=1, columnspan=3, sticky=tk.W)

        # --- Modem / PTC -------------------------------------------------
        f_ptc = ttk.LabelFrame(outer, text="Modem / PTC  (Funkgerät am Modem → PTT Methode TNC)", padding=8)
        f_ptc.pack(fill=tk.X, pady=4)
        self.cb_ptc_port = self._combo(f_ptc, 0, "PTC COM Port:", list_serial_ports(), cfg.get("PTC_SERIAL_PORT", ""),
                                       editable=True)
        ttk.Button(f_ptc, text="↻", width=3, command=self._refresh_ports).grid(row=0, column=2, padx=4)
        self.cb_ptc_baud = self._combo(f_ptc, 1, "PTC Baudrate:", [str(b) for b in PTC_BAUD_RATES],
                                       str(cfg.get("PTC_BAUD", 57600)))
        self.cb_ptc_type = self._combo(f_ptc, 2, "PTC Modemtyp:", list(PTC_MODEM_TYPES),
                                       str(cfg.get("PTC_MODEM_TYPE", "AUTO")))

        # --- CAT / RIG ---------------------------------------------------
        f_cat = ttk.LabelFrame(outer, text="CAT / RIG  (Funkgerät direkt am PC)", padding=8)
        f_cat.pack(fill=tk.X, pady=4)
        self.cb_rig_port = self._combo(f_cat, 0, "RIG COM Port:", list_serial_ports(), cfg.get("RIG_SERIAL_PORT", ""),
                                       editable=True)
        ttk.Button(f_cat, text="↻", width=3, command=self._refresh_ports).grid(row=0, column=2, padx=4)
        self.cb_rig_baud = self._combo(f_cat, 1, "RIG Baudrate:", [str(b) for b in RIG_BAUD_RATES],
                                       str(cfg.get("RIG_BAUD", 115200)))
        ttk.Label(f_cat, text="CI-V Adresse (HEX):").grid(row=2, column=0, sticky=tk.W, pady=2)
        self.e_civ = ttk.Entry(f_cat, width=8)
        self.e_civ.insert(0, str(cfg.get("CAT_ADDRESS", "94")))
        self.e_civ.grid(row=2, column=1, sticky=tk.W, pady=2)
        self.cb_proto = self._combo(f_cat, 3, "Protokoll:", list(CAT_PROTOCOLS), str(cfg.get("CAT_PROTOCOL", "ICOM")))

        # --- TNC / PTT ---------------------------------------------------
        f_ptt = ttk.LabelFrame(outer, text="TNC / PTT", padding=8)
        f_ptt.pack(fill=tk.X, pady=4)
        self.cb_ptt = self._combo(f_ptt, 0, "PTT Methode:", list(PTT_METHODS), str(cfg.get("PTT_METHOD", "CAT")))
        ttk.Label(f_ptt, text="PTT Vorlauf (ms):").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.sp_delay = ttk.Spinbox(f_ptt, from_=0, to=3000, increment=50, width=8)
        self.sp_delay.set(str(cfg.get("PTT_DELAY_MS", 300)))
        self.sp_delay.grid(row=1, column=1, sticky=tk.W, pady=2)
        ttk.Label(f_ptt, foreground="gray", justify=tk.LEFT, text=(
            "CAT: PTT-Befehl über den RIG Port (Icom CI-V, Yaesu, Kenwood)\n"
            "TNC: Funkgerät hängt am Modem – nur Codan (Selcall per CICS über das Modem)\n"
            "RTS / DTR: Leitung am RIG Port (Interface, IC-7300 USB SEND)\n"
            "VOX: keine PTT, Funkgerät schaltet selbst")).grid(row=2, column=0, columnspan=3, sticky=tk.W)

        # --- Audio -------------------------------------------------------
        f_audio = ttk.LabelFrame(outer, text="Audio (für Selcall vom PC, z.B. IC-7300 USB Audio CODEC)", padding=8)
        f_audio.pack(fill=tk.X, pady=4)
        self.cb_out = self._combo(f_audio, 0, "Ausgang (TX):", [""] + audio_devices("out"), cfg.get("AUDIO_OUT", ""),
                                  width=40)
        self.cb_in = self._combo(f_audio, 1, "Eingang (RX):", [""] + audio_devices("in"), cfg.get("AUDIO_IN", ""),
                                 width=40)
        f_atest = ttk.Frame(f_audio)
        f_atest.grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=(4, 0))
        ttk.Button(f_atest, text="Nur Soundkarte suchen", command=self._auto_audio).pack(side=tk.LEFT)
        ttk.Button(f_atest, text="🔊 Testton 2 s (mit PTT)", command=self._test_tone).pack(side=tk.LEFT, padx=6)
        ttk.Button(f_atest, text="PTT-Test 1 s", command=self._test_ptt).pack(side=tk.LEFT)
        ttk.Button(f_atest, text="Alle Audiogeräte ins Protokoll", command=self._log_audio_devices).pack(
            side=tk.LEFT, padx=6)
        f_atest2 = ttk.Frame(f_audio)
        f_atest2.grid(row=5, column=0, columnspan=3, sticky=tk.W, pady=(4, 0))
        ttk.Button(f_atest2, text="🎯 Per Sendetest finden (Icom)", command=self._find_by_tx).pack(side=tk.LEFT)
        ttk.Button(f_atest2, text="Funkgerät auf USB-D stellen", command=self._set_usb_data).pack(
            side=tk.LEFT, padx=6)
        ttk.Button(f_atest2, text="Ton ohne PTT abspielen", command=self._tone_no_ptt).pack(side=tk.LEFT)
        ttk.Label(f_audio, foreground="gray", justify=tk.LEFT, text=(
            "Sendetest: spielt nacheinander auf jeder Soundkarte einen Ton und liest dabei die Leistung\n"
            "des Funkgeräts – die Karte mit Leistung ist die richtige.  'Ton ohne PTT': hörst du ihn\n"
            "am PC, ist es NICHT die Funkgeräte-Soundkarte.")).grid(row=6, column=0, columnspan=3, sticky=tk.W)
        if sd is None:
            ttk.Label(f_audio, foreground="red", text=(
                "Modul 'sounddevice' fehlt – darum sind die Listen leer.\n"
                "Installieren:  py -m pip install sounddevice  (dann Programm neu starten)")).grid(
                row=4, column=0, columnspan=3, sticky=tk.W)
        ttk.Label(f_audio, foreground="gray", justify=tk.LEFT, text=(
            "Testton: das Funkgerät muss senden und die ALC/Leistung ausschlagen.\n"
            "Richtiger Eingang: RX Decoder starten – der Pegel zeigt das Rauschen des Empfängers.")).grid(
            row=3, column=0, columnspan=3, sticky=tk.W)

        # --- Codan -------------------------------------------------------
        f_codan = ttk.LabelFrame(outer, text="CODAN Selcall", padding=8)
        f_codan.pack(fill=tk.X, pady=4)
        ttk.Label(f_codan, text="Eigene ID:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.e_our = ttk.Entry(f_codan, width=10)
        self.e_our.insert(0, str(cfg.get("OUR_ID", "")))
        self.e_our.grid(row=0, column=1, sticky=tk.W, pady=2)
        self.cb_mode = self._combo(f_codan, 1, "Selcall erzeugt:", ["AUTO", "CICS", "AUDIO"],
                                   str(cfg.get("CODAN_MODE", "AUTO")))
        ttk.Label(f_codan, foreground="gray", text="AUTO: Codan → Funkgerät selbst (CICS), andere → PC (Audio)").grid(
            row=2, column=0, columnspan=3, sticky=tk.W)
        self.e_cmds = {}
        row = 3
        for kind, (key, default, name) in CODAN_CALLS.items():
            ttk.Label(f_codan, text=f"CICS {name}:").grid(row=row, column=0, sticky=tk.W, pady=1)
            entry = ttk.Entry(f_codan, width=30)
            entry.insert(0, str(cfg.get(key, default) or default))
            entry.grid(row=row, column=1, columnspan=2, sticky=tk.W, pady=1)
            self.e_cmds[key] = (entry, default)
            row += 1
        self.v_from = tk.BooleanVar(value=bool(cfg.get("CODAN_SEND_SELF_ID", False)))
        ttk.Checkbutton(f_codan, text="eigene ID mitsenden („from <ID>“)", variable=self.v_from).grid(
            row=row, column=1, columnspan=2, sticky=tk.W)
        ttk.Label(f_codan, foreground="gray",
                  text="{to} = gerufene Station, {self} = eigene ID, {msg} = Nachricht").grid(
            row=row + 1, column=0, columnspan=3, sticky=tk.W)

        self.v_auto = tk.BooleanVar(value=bool(cfg.get("AUTO_CONNECT", True)))
        ttk.Checkbutton(outer, text="Beim Start automatisch verbinden", variable=self.v_auto).pack(anchor=tk.W)

        self._show_profile()

    def _on_wheel(self, event):
        # an open combobox list scrolls itself
        if str(event.widget).endswith("popdown.f.l"):
            return
        self._canvas.yview_scroll(int(-event.delta / 120) or (-1 if event.delta > 0 else 1), "units")

    def _current_values(self) -> dict:
        try:
            delay = max(0, int(float(self.sp_delay.get())))
        except ValueError:
            delay = 300
        radio = self.cb_radio.get()
        return {
            "RADIO_MODEL": "" if radio == "(manuell)" else radio,
            "PTC_SERIAL_PORT": self.cb_ptc_port.get().strip(),
            "PTC_BAUD": int(self.cb_ptc_baud.get()),
            "PTC_MODEM_TYPE": self.cb_ptc_type.get(),
            "RIG_SERIAL_PORT": self.cb_rig_port.get().strip(),
            "RIG_BAUD": int(self.cb_rig_baud.get()),
            "CAT_ADDRESS": (self.e_civ.get().strip().lstrip("$") or "94").upper(),
            "CAT_PROTOCOL": self.cb_proto.get(),
            "PTT_METHOD": self.cb_ptt.get(),
            "PTT_DELAY_MS": delay,
            "AUDIO_OUT": self.cb_out.get(),
            "AUDIO_IN": self.cb_in.get(),
        }

    def _apply_found(self, found: dict):
        setters = {
            "PTC_SERIAL_PORT": self.cb_ptc_port, "PTC_BAUD": self.cb_ptc_baud, "PTC_MODEM_TYPE": self.cb_ptc_type,
            "RIG_SERIAL_PORT": self.cb_rig_port, "RIG_BAUD": self.cb_rig_baud,
            "AUDIO_OUT": self.cb_out, "AUDIO_IN": self.cb_in,
        }
        for key, widget in setters.items():
            if key in found:
                widget.set(str(found[key]))
        if "CAT_ADDRESS" in found:
            self.e_civ.delete(0, tk.END)
            self.e_civ.insert(0, str(found["CAT_ADDRESS"]))

    def _auto_detect(self, audio_only: bool = False):
        values = self._current_values()
        is_codan = values["CAT_PROTOCOL"].upper() == "CODAN"
        via_modem = values["PTT_METHOD"].upper() == "TNC"
        # free the ports this program holds; other programs (HFChat) must be closed
        self.app.link.disconnect()
        self.app._update_connection_label()
        self.btn_auto.config(state="disabled")
        self.lbl_auto.config(text="Suche läuft … (bis zu 1 Minute)")
        outputs, inputs = audio_devices("out"), audio_devices("in")

        def _work():
            try:
                found = autodetect.detect(values, outputs, inputs, self.app.log,
                                          want_rig=not audio_only and not (is_codan and via_modem),
                                          want_ptc=not audio_only and (via_modem or is_codan))
            except Exception as exc:
                found = {}
                self.app.log(f"Automatische Erkennung: Fehler {exc}")

            def _done():
                if not self.winfo_exists():
                    return
                self.btn_auto.config(state="normal")
                self._apply_found(found)
                parts = []
                if "RIG_SERIAL_PORT" in found:
                    parts.append(f"Funkgerät {found['RIG_SERIAL_PORT']} @ {found['RIG_BAUD']}")
                if "PTC_SERIAL_PORT" in found:
                    parts.append(f"Modem {found['PTC_SERIAL_PORT']} @ {found['PTC_BAUD']}")
                if "AUDIO_OUT" in found:
                    parts.append(f"Audio {found['AUDIO_OUT']}")
                self.lbl_auto.config(text=("Gefunden: " + " | ".join(parts) + " – bitte Speichern")
                                     if parts else "Nichts gefunden – Details im Protokoll")
            self.after(0, _done)
        threading.Thread(target=_work, daemon=True).start()

    def _auto_audio(self):
        self._auto_detect(audio_only=True)

    def _test_tone(self):
        """2 s 1000 Hz with PTT using the values shown in the dialog (not yet saved)."""
        if not messagebox.askyesno("Testton", "Das Funkgerät sendet 2 Sekunden einen 1000-Hz-Ton.\n"
                                              "Antenne/Dummy Load angeschlossen und Frequenz frei?", parent=self):
            return
        values = self._current_values()
        self.app.cfg.update(values)
        self.app.link.disconnect()
        problems = self.app.link.connect()
        for problem in problems:
            self.app.log(f"FEHLER: {problem}")
        self.app._update_connection_label()
        tone = self.app.audio_gen.generate_sine_wave(1000, 2000, amplitude=0.5)
        self.app.play_audio_with_ptt(self.app.audio_gen.create_wav_bytes(tone), "Testton 1000 Hz")

    def _prepare_link(self):
        self.app.cfg.update(self._current_values())
        self.app.link.disconnect()
        for problem in self.app.link.connect():
            self.app.log(f"FEHLER: {problem}")
        self.app._update_connection_label()

    def _find_by_tx(self):
        self._prepare_link()

        def _done(out_name, in_name):
            if self.winfo_exists():
                self.cb_out.set(out_name)
                if in_name:
                    self.cb_in.set(in_name)
        self.app.find_radio_soundcard(done=_done)

    def _set_usb_data(self):
        self._prepare_link()
        problem = self.app.link.icom_set_usb_data()
        if problem:
            messagebox.showwarning("USB-D", f"{problem}\nAm Funkgerät die DATA-Taste drücken.", parent=self)
        else:
            messagebox.showinfo("USB-D", "Funkgerät steht auf USB-D.", parent=self)

    def _tone_no_ptt(self):
        name = self.cb_out.get()
        idx = audio_device_index(name, "out")
        if sd is None or idx is None:
            messagebox.showerror("Audio", "Bitte zuerst einen Ausgang wählen.", parent=self)
            return
        tone = np.frombuffer(bytes(self.app.audio_gen.generate_sine_wave(1000, 1500, amplitude=0.3)),
                             dtype="<i2").astype(np.float32) / 32768.0
        try:
            sd.play(tone, samplerate=self.app.audio_gen.sample_rate, device=idx)
        except Exception as exc:
            messagebox.showerror("Audio", str(exc), parent=self)
            return
        self.app.log(f"Ton ohne PTT auf: {name} – hörst du ihn am PC, ist es die falsche Karte")

    def _log_audio_devices(self):
        log = self.app.log
        if sd is None:
            log("Audio: Modul 'sounddevice' fehlt – py -m pip install sounddevice")
            return
        try:
            apis = sd.query_hostapis()
            for i, dev in enumerate(sd.query_devices()):
                api = apis[dev["hostapi"]]["name"] if dev["hostapi"] < len(apis) else "?"
                log(f"Audio {i:2d} [{api}] in={dev['max_input_channels']} out={dev['max_output_channels']} "
                    f"{dev['name']}")
        except Exception as exc:
            log(f"Audio: Geräte nicht lesbar: {exc}")
        log(f"Auswahlliste Ausgang: {audio_devices('out')}")
        log(f"Erkannt als Funkgerät: {autodetect.guess_by_name(audio_devices('out'))}")

    def _test_ptt(self):
        if not messagebox.askyesno("PTT-Test", "Das Funkgerät geht 1 Sekunde auf Senden (ohne Ton).\n"
                                               "Antenne/Dummy Load angeschlossen?", parent=self):
            return
        self._prepare_link()

        def _work():
            if self.app.link.set_ptt(True):
                time.sleep(1.0)
            self.app.link.set_ptt(False)
        threading.Thread(target=_work, daemon=True).start()

    def _combo(self, parent, row, label, values, current, editable=False, width=14):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky=tk.W, pady=2)
        combo = ttk.Combobox(parent, values=values, width=width, state="normal" if editable else "readonly")
        combo.set(current)
        combo.grid(row=row, column=1, sticky=tk.W, pady=2)
        return combo

    def _refresh_ports(self):
        ports = list_serial_ports()
        self.cb_ptc_port["values"] = ports
        self.cb_rig_port["values"] = ports

    def _show_profile(self):
        profile = self.app.profiles.get(self.cb_radio.get())
        self.lbl_profile.config(text=profile.summary() if profile else "Protokoll / Baudrate unten selbst einstellen")

    def _apply_radio_model(self):
        """Like HFChat: the radio model fills protocol, CI-V address and baud rate."""
        profile = self.app.profiles.get(self.cb_radio.get())
        self._show_profile()
        if profile is None:
            return
        self.cb_proto.set(profile.cat_protocol())
        if profile.address is not None:
            self.e_civ.delete(0, tk.END)
            self.e_civ.insert(0, f"{profile.address:02X}")
        if profile.is_codan:
            self.cb_rig_baud.set(str(profile.baudrate))
            if self.cb_ptt.get() not in ("CAT", "TNC"):
                self.cb_ptt.set("TNC")

    def _save(self):
        our = self.e_our.get().strip()
        if our and not (our.isdigit() and len(our) in (4, 6)):
            messagebox.showerror("Einstellungen", "Eigene ID: 4 oder 6 Ziffern (z.B. 435299).", parent=self)
            return
        civ = self.e_civ.get().strip().lstrip("$") or "94"
        try:
            int(civ, 16)
        except ValueError:
            messagebox.showerror("Einstellungen", "CI-V Adresse muss hexadezimal sein (z.B. 94).", parent=self)
            return
        cfg = self.app.cfg
        cfg.update(self._current_values())
        cfg.update({
            "OUR_ID": our,
            "CODAN_MODE": self.cb_mode.get(),
            **{key: (entry.get().strip() or default) for key, (entry, default) in self.e_cmds.items()},
            "CODAN_SEND_SELF_ID": bool(self.v_from.get()),
            "AUTO_CONNECT": bool(self.v_auto.get()),
        })
        try:
            save_config(cfg)
        except OSError as exc:
            messagebox.showerror("Einstellungen", f"settings.json konnte nicht gespeichert werden: {exc}", parent=self)
            return
        self.app.on_settings_saved()
        self.destroy()


# =============================================================================
# Main window
# =============================================================================
class SelCallApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SelCall Terminal")
        self.geometry(f"660x{max(520, min(800, self.winfo_screenheight() - 80))}")
        self.cfg = load_config()
        self.profiles = radio_models.load_models(APP_DIR)
        self.audio_gen = AudioGenerator()
        self.codan_encoder = CodanSelcallEncoder()
        self.link = RadioLink(self.cfg, self.log, self.profiles.get)
        self.link.on_radio_line = self.on_radio_line
        self.tx_lock = threading.Lock()
        self.decoder_engine = AudioDecoderEngine(self.on_decoder_event)

        self._build_menu()
        self._build_connection_bar()
        self._build_tabs()
        self._build_log()
        ttk.Label(self, text="Frederic Tartarone © 2026", padding=(10, 2)).pack(side=tk.BOTTOM, anchor=tk.E)

        self.protocol("WM_DELETE_WINDOW", self._quit)
        self.after(200, self._startup)

    # ---------------------------------------------------------------- layout
    def _build_menu(self):
        bar = tk.Menu(self)
        m_file = tk.Menu(bar, tearoff=0)
        m_file.add_command(label="Einstellungen…", command=self.open_settings)
        m_file.add_separator()
        m_file.add_command(label="Beenden", command=self._quit)
        bar.add_cascade(label="Datei", menu=m_file)
        self.config(menu=bar)

    def _build_connection_bar(self):
        frame = ttk.LabelFrame(self, text="Verbindung zum Funkgerät", padding=8)
        frame.pack(fill=tk.X, padx=10, pady=(8, 4))
        self.lbl_radio = ttk.Label(frame, text="", font=("Segoe UI", 10, "bold"))
        self.lbl_radio.grid(row=0, column=0, sticky=tk.W)
        self.lbl_status = ttk.Label(frame, text="", foreground="gray")
        self.lbl_status.grid(row=1, column=0, sticky=tk.W)
        self.btn_connect = ttk.Button(frame, text="Verbinden", command=self.toggle_connection)
        self.btn_connect.grid(row=0, column=1, rowspan=2, padx=6)
        ttk.Button(frame, text="⚙ Einstellungen", command=self.open_settings).grid(row=0, column=2, rowspan=2)
        frame.columnconfigure(0, weight=1)

        cmd = ttk.Frame(frame)
        cmd.grid(row=2, column=0, columnspan=3, sticky=tk.EW, pady=(6, 0))
        ttk.Label(cmd, text="Befehl an Funkgerät/Modem:").pack(side=tk.LEFT)
        self.e_raw = ttk.Entry(cmd, width=28)
        self.e_raw.pack(side=tk.LEFT, padx=4)
        self.e_raw.bind("<Return>", lambda _e: self.send_raw_command())
        ttk.Button(cmd, text="Senden", command=self.send_raw_command).pack(side=tk.LEFT)
        self._update_connection_label()

    def _build_tabs(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        self.tab_codan = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_codan, text="CODAN")
        self._build_codan_tab()
        self.tab_tone = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_tone, text="Tone SelCall")
        self._build_tone_tab()
        self.tab_necode = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_necode, text="Necode")
        self._build_necode_tab()

    def _build_log(self):
        frame = ttk.LabelFrame(self, text="Protokoll", padding=6)
        frame.pack(fill=tk.BOTH, expand=False, padx=10, pady=4)
        top = ttk.Frame(frame)
        top.pack(fill=tk.X)
        ttk.Label(top, text="RX Pegel:").pack(side=tk.LEFT)
        self.progress_level = ttk.Progressbar(top, length=120, mode="determinate")
        self.progress_level.pack(side=tk.LEFT, padx=4)
        self.btn_rx = ttk.Button(top, text="RX Decoder Start", command=self.toggle_rx_engine)
        self.btn_rx.pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="Log leeren", command=self.clear_log).pack(side=tk.RIGHT)
        self.entry_rx_seq = ttk.Entry(top, width=14)
        self.entry_rx_seq.pack(side=tk.RIGHT, padx=4)
        self.txt_log = tk.Text(frame, height=10, width=70, state="disabled", font=("Consolas", 9))
        self.txt_log.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

    def _build_codan_tab(self):
        top = ttk.Frame(self.tab_codan, padding=(10, 6))
        top.pack(fill=tk.X)
        self.codan_priority = tk.StringVar(value="Routine")
        for p in CodanSelcallEncoder.CATEGORIES:
            ttk.Radiobutton(top, text=p, value=p, variable=self.codan_priority, style="Toolbutton").pack(
                side=tk.LEFT, padx=2)

        form = ttk.Frame(self.tab_codan, padding=(10, 2))
        form.pack(fill=tk.X)
        ttk.Label(form, text="Station (4/6 Ziffern):").grid(row=0, column=0, sticky=tk.W, pady=3)
        self.codan_call_id = ttk.Entry(form, width=10, font=("Segoe UI", 12))
        self.codan_call_id.grid(row=0, column=1, sticky=tk.W, padx=6, pady=3)
        self.codan_call_id.bind("<Return>", lambda _e: self.send_codan("selcall"))
        self.lbl_our_id = ttk.Label(form, text="", foreground="gray")
        self.lbl_our_id.grid(row=0, column=2, sticky=tk.W, padx=6)

        ttk.Label(form, text="Nachricht (SMS):").grid(row=1, column=0, sticky=tk.W, pady=3)
        self.codan_msg = ttk.Entry(form, width=40)
        self.codan_msg.grid(row=1, column=1, columnspan=2, sticky=tk.W, padx=6, pady=3)
        self.codan_msg.bind("<KeyRelease>", lambda _e: self._update_msg_count())
        self.codan_msg.bind("<Return>", lambda _e: self.send_codan("page"))
        self.lbl_msg_count = ttk.Label(form, text="", foreground="gray")
        self.lbl_msg_count.grid(row=1, column=3, sticky=tk.W)

        buttons = ttk.Frame(self.tab_codan, padding=(10, 4))
        buttons.pack(fill=tk.X)
        for text, kind in (("📞 Anpagern (Selcall)", "selcall"), ("✉ Nachricht senden", "page"),
                           ("❓ Status abfragen", "status"), ("📍 GPS abfragen", "gps"),
                           ("Kanaltest", "beacon"), ("Auflegen", "hangup")):
            ttk.Button(buttons, text=text, command=lambda k=kind: self.send_codan(k)).pack(
                side=tk.LEFT, padx=(0, 4), ipady=3)

        opts = ttk.Frame(self.tab_codan, padding=(10, 2))
        opts.pack(fill=tk.X)
        ttk.Label(opts, text="Vorspann bei Audio (s):").pack(side=tk.LEFT)
        self.codan_preamble = ttk.Spinbox(opts, from_=0.5, to=30, increment=0.5, width=5)
        self.codan_preamble.set(str(self.cfg.get("CODAN_PREAMBLE_S", 2.0)))
        self.codan_preamble.pack(side=tk.LEFT, padx=4)
        ttk.Label(opts, text="2 s auf Kanal · 6–12 s Gegenstation scannt", foreground="gray").pack(side=tk.LEFT)

        self.lbl_codan_path = ttk.Label(self.tab_codan, text="", foreground="gray", justify=tk.LEFT,
                                        padding=(10, 2))
        self.lbl_codan_path.pack(fill=tk.X)

        inbox = ttk.LabelFrame(self.tab_codan, text="Eingang (Doppelklick = Station übernehmen)", padding=4)
        inbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        cols = ("zeit", "art", "von", "an", "text")
        self.tree_inbox = ttk.Treeview(inbox, columns=cols, show="headings", height=5)
        for col, title, width in (("zeit", "Zeit", 60), ("art", "Art", 140), ("von", "Von", 70),
                                  ("an", "An", 70), ("text", "Text / Inhalt", 250)):
            self.tree_inbox.heading(col, text=title)
            self.tree_inbox.column(col, width=width, anchor=tk.W, stretch=(col == "text"))
        self.tree_inbox.tag_configure("mine", background="#fff2cc")
        self.tree_inbox.pack(fill=tk.BOTH, expand=True)
        self.tree_inbox.bind("<Double-1>", self._take_station_from_inbox)
        self._update_codan_labels()
        self._update_msg_count()

    def _update_msg_count(self):
        n = len(self.codan_msg.get())
        limit = CodanSelcallEncoder.PAGE_MAX_CHARS if not self._codan_uses_cics() else 64
        self.lbl_msg_count.config(text=f"{n}/{limit}", foreground="red" if n > limit else "gray")

    def _take_station_from_inbox(self, _event):
        sel = self.tree_inbox.selection()
        if sel:
            station = self.tree_inbox.item(sel[0], "values")[2]
            if station and station.isdigit():
                self.codan_call_id.delete(0, tk.END)
                self.codan_call_id.insert(0, station)

    def add_inbox(self, kind: str, frm: str = "", to: str = "", text: str = ""):
        def _do():
            mine = bool(to) and to == str(self.cfg.get("OUR_ID", ""))
            self.tree_inbox.insert("", 0, values=(time.strftime("%H:%M:%S"), kind, frm, to, text),
                                   tags=("mine",) if mine else ())
            if mine:
                self.bell()
        self.after(0, _do)

    def on_radio_line(self, port: str, text: str):
        """Lines the Codan prints by itself (incoming calls, messages, status)."""
        if self.link.is_echo(text):
            return    # echo of our own command / modem prompt
        upper = text.upper()
        if upper.startswith(("TRX ", "PTC ")) or " FREQUENCY CHANGED" in upper:
            return
        if any(word in upper for word in ("CALL", "MSG", "MESSAGE", "PAGE", "STATUS", "GPS", "POSITION",
                                          "BEACON", "SELCALL")):
            self.add_inbox(f"Codan meldet ({port})", text=text)

    def _build_tone_tab(self):
        top = ttk.Frame(self.tab_tone, padding=10)
        top.pack(fill=tk.X)
        self.mode_var = tk.StringVar(value="ZVEI1")
        self.mode_combo = ttk.Combobox(top, textvariable=self.mode_var, values=list(TONE_STANDARDS.keys()),
                                       state="readonly", width=15)
        self.mode_combo.pack(anchor=tk.W, pady=5)
        self.mode_combo.bind("<<ComboboxSelected>>", self.on_mode_change)
        seq = ttk.Frame(self.tab_tone, padding=10)
        seq.pack(fill=tk.X)
        self.tone_seq_entry = ttk.Entry(seq, width=25)
        self.tone_seq_entry.insert(0, "12345")
        self.tone_seq_entry.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(seq, text="Senden", command=self.play_tone_seq).pack(side=tk.LEFT)
        ttk.Button(seq, text="Löschen", command=lambda: self.tone_seq_entry.delete(0, tk.END)).pack(
            side=tk.LEFT, padx=4)
        self.keypad_frame = ttk.Frame(self.tab_tone, padding=10)
        self.keypad_frame.pack(fill=tk.BOTH, expand=True)
        self.on_mode_change(None)

    def _build_necode_tab(self):
        form = ttk.Frame(self.tab_necode, padding=20)
        form.pack(fill=tk.BOTH, expand=True)
        ttk.Label(form, text="Call ID:").grid(row=0, column=0, sticky=tk.W, pady=10)
        self.necode_call_id = ttk.Entry(form, width=15)
        self.necode_call_id.insert(0, "1234")
        self.necode_call_id.grid(row=0, column=1, sticky=tk.W, padx=10, pady=10)
        ttk.Button(form, text="Senden", command=self.send_necode).grid(row=1, column=1, sticky=tk.W, padx=10)

    # ------------------------------------------------------------ helpers
    def log(self, text: str):
        def _do():
            self.txt_log.config(state="normal")
            self.txt_log.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {text}\n")
            self.txt_log.see(tk.END)
            self.txt_log.config(state="disabled")
        try:
            self.after(0, _do)
        except RuntimeError:
            pass

    def clear_log(self):
        self.entry_rx_seq.delete(0, tk.END)
        self.txt_log.config(state="normal")
        self.txt_log.delete("1.0", tk.END)
        self.txt_log.config(state="disabled")

    def _codan_uses_cics(self) -> bool:
        mode = str(self.cfg.get("CODAN_MODE", "AUTO")).upper()
        if mode == "CICS":
            return True
        if mode == "AUDIO":
            return False
        return self.link.is_codan

    def _update_connection_label(self):
        radio = self.cfg.get("RADIO_MODEL") or f"manuell ({self.cfg.get('CAT_PROTOCOL', 'ICOM')})"
        self.lbl_radio.config(text=f"Funkgerät: {radio}")
        self.lbl_status.config(text=self.link.status_text())
        self.btn_connect.config(text="Trennen" if (self.link.rig.is_open or self.link.ptc.is_open) else "Verbinden")

    def _update_codan_labels(self):
        self.lbl_our_id.config(text=f"eigene ID: {self.cfg.get('OUR_ID') or '– (Einstellungen)'}")
        method = self.link.ptt_method
        if self._codan_uses_cics():
            way = "über das Modem (TRX T …)" if method == "TNC" else "direkt am RIG Port"
            text = (f"Weg: Codan sendet den Selcall selbst – CICS-Befehl {way}.\n"
                    f"Befehl: {self.link.codan_command_text('selcall', '<ID>', str(self.cfg.get('OUR_ID', '')))}")
        else:
            text = (f"Weg: PC erzeugt CCIR 493-4 (100 Bd FSK 1700/1870 Hz), PTT {method}.\n"
                    "Funkgerät in USB (IC-7300: USB-D, DATA MOD = USB).")
        self.lbl_codan_path.config(text=text)

    # --------------------------------------------------------- connection
    def _startup(self):
        if not self.cfg.get("RADIO_MODEL") and not self.cfg.get("RIG_SERIAL_PORT") \
                and not self.cfg.get("PTC_SERIAL_PORT"):
            self.log("Bitte zuerst Einstellungen öffnen: Funkgerät, COM Port, PTT Methode")
            self.open_settings()
            return
        self._auto_audio_if_missing()
        if self.cfg.get("AUTO_CONNECT", True):
            self.connect()
        if not self._codan_uses_cics() and self.cfg.get("AUDIO_IN"):
            self.after(1500, self.start_rx_engine)     # hear answers and incoming calls

    def _auto_audio_if_missing(self):
        """No (or a vanished) sound card set: find the radio's sound card by itself."""
        if self._codan_uses_cics():
            return   # Codan sends its own selcall, the PC sound card is not used
        if audio_device_index(self.cfg.get("AUDIO_OUT", ""), "out") is not None:
            return
        outputs, inputs = audio_devices("out"), audio_devices("in")

        def _work():
            found = {}
            rig = str(self.cfg.get("RIG_SERIAL_PORT", "") or "")
            tree = autodetect.windows_device_tree() if rig else []
            if tree:
                win_out, win_in = autodetect.audio_for_com_port(rig, tree)
                found["AUDIO_OUT"] = autodetect.match_name(win_out, outputs)
                found["AUDIO_IN"] = autodetect.match_name(win_in, inputs)
            if not found.get("AUDIO_OUT"):
                found["AUDIO_OUT"] = autodetect.guess_by_name(outputs)
            if found["AUDIO_OUT"] and not found.get("AUDIO_IN"):
                found["AUDIO_IN"] = autodetect.pick_partner(inputs, found["AUDIO_OUT"]) or \
                    autodetect.guess_by_name(inputs)

            def _done():
                if not found.get("AUDIO_OUT"):
                    self.log("Keine Funkgeräte-Soundkarte gefunden – Einstellungen → Audio")
                    return
                self.cfg["AUDIO_OUT"] = found["AUDIO_OUT"]
                if found.get("AUDIO_IN"):
                    self.cfg["AUDIO_IN"] = found["AUDIO_IN"]
                self.log(f"Soundkarte automatisch gewählt: TX {self.cfg['AUDIO_OUT']} | RX {self.cfg.get('AUDIO_IN')}")
                try:
                    save_config(self.cfg)
                except OSError:
                    pass
            self.after(0, _done)
        threading.Thread(target=_work, daemon=True).start()

    def connect(self):
        self.btn_connect.config(state="disabled")

        def _work():
            problems = self.link.connect()

            def _done():
                self.btn_connect.config(state="normal")
                self._update_connection_label()
                for problem in problems:
                    self.log(f"FEHLER: {problem}")
                if problems:
                    messagebox.showwarning("Verbindung", "\n".join(problems))
            self.after(0, _done)
        threading.Thread(target=_work, daemon=True).start()

    def toggle_connection(self):
        if self.link.rig.is_open or self.link.ptc.is_open:
            self.link.disconnect()
            self._update_connection_label()
        else:
            self.connect()

    def open_settings(self):
        SettingsDialog(self)

    def on_settings_saved(self):
        self.log("Einstellungen gespeichert")
        was_connected = self.link.rig.is_open or self.link.ptc.is_open
        self.link.disconnect()
        self._update_codan_labels()
        self._update_connection_label()
        if was_connected or self.cfg.get("AUTO_CONNECT", True):
            self.connect()

    def send_raw_command(self):
        """Free text command for tests, e.g. Codan CICS 'ver' or PTC 'VER'."""
        text = self.e_raw.get().strip()
        if not text:
            return

        def _work():
            if self.link.ptt_method == "TNC" and self.link.ptc.is_open:
                self.link.ptc.write((text + "\r").encode("latin-1", errors="ignore"))
                self.log(f"PTC ← {text}")
            elif self.link.rig.is_open:
                self.link.rig.write((text + "\r").encode("latin-1", errors="ignore"))
                self.log(f"RIG ← {text}")
            else:
                self.log("Nicht verbunden")
        threading.Thread(target=_work, daemon=True).start()
        self.e_raw.delete(0, tk.END)

    # --------------------------------------------------------------- TX
    def play_audio_with_ptt(self, wav_bytes: bytes, label: str, listen_after: bool = False):
        problem = self.link.can_key_audio()
        if problem:
            self.log(f"FEHLER: {problem}")
            messagebox.showerror("Senden nicht möglich", problem)
            return
        if sd is None:
            messagebox.showerror("Audio", "sounddevice ist nicht installiert (py -m pip install sounddevice)")
            return
        out_name = self.cfg.get("AUDIO_OUT", "")
        out_dev = audio_device_index(out_name, "out")
        if out_dev is None:
            guess = autodetect.guess_by_name(audio_devices("out"))
            if guess:
                self.log(f"Audio-Ausgang {'fehlt' if not out_name else repr(out_name) + ' nicht gefunden'} – "
                         f"nehme {guess}")
                out_name, out_dev = guess, audio_device_index(guess, "out")
        if out_dev is None:
            # Never play on the Windows default device: that is the PC speaker.
            why = (f"Die Soundkarte '{out_name}' gibt es gerade nicht" if out_name
                   else "Es ist keine Funkgeräte-Soundkarte eingestellt")
            self.log(f"NICHT gesendet: {why}")
            if messagebox.askyesno("Soundkarte fehlt", f"{why} – der Ton würde sonst am PC herauskommen.\n\n"
                                   "Jetzt die Soundkarte des Funkgeräts suchen?\n"
                                   "(Einstellungen öffnen → 'Per Sendetest finden')"):
                self.open_settings()
            return
        self.log(f"Ton geht an: {out_name}")
        if not self.tx_lock.acquire(blocking=False):
            self.log("Sender belegt – bitte warten")
            return
        rx_running = self.decoder_engine.is_running

        def _play():
            try:
                if rx_running:
                    self.decoder_engine.stop()
                with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                    rate = wf.getframerate()
                    frames = wf.readframes(wf.getnframes())
                samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
                self.log(f"TX {label} ({len(samples) / rate:.1f} s)")
                if not self.link.set_ptt(True):
                    self.log("FEHLER: PTT konnte nicht geschaltet werden")
                    return
                time.sleep(max(0, int(self.cfg.get("PTT_DELAY_MS", 300))) / 1000.0)
                try:
                    sd.play(samples, samplerate=rate, device=out_dev)
                    self._check_tx_audio(len(samples) / rate)
                    sd.wait()
                except Exception as exc:
                    self.log(f"Audio Fehler: {exc}")
                time.sleep(0.15)
            finally:
                self.link.set_ptt(False)
                if rx_running or (listen_after and self.cfg.get("AUDIO_IN")):
                    self.after(0, self.start_rx_engine)
                self.tx_lock.release()

        threading.Thread(target=_play, daemon=True).start()

    def _check_tx_audio(self, duration: float):
        """Icom: read ALC/Po during TX - shows at once whether the tone reaches the radio."""
        if self.link.ptt_method != "CAT" or self.link.cat_protocol.upper() != "ICOM" or duration < 0.8:
            return
        time.sleep(0.5)
        po, alc = self.link.icom_meter("PO"), self.link.icom_meter("ALC")
        if po is None and alc is None:
            return
        self.log(f"Während TX: Leistung {po} / ALC {alc} (0–255)")
        if not po and not alc:
            self.log("WARNUNG: kein Ton am Funkgerät (Leistung 0) – falsche Soundkarte, oder am IC-7300 "
                     "nicht USB-D / DATA MOD ≠ USB / USB MOD Level 0 %")

    def find_radio_soundcard(self, done=None):
        """Icom with CAT: key up, play a tone on each sound card, read the power.
        The card that makes power is the radio's."""
        if self.link.ptt_method != "CAT" or self.link.cat_protocol.upper() != "ICOM":
            messagebox.showinfo("Sendetest", "Der Sendetest braucht ein Icom mit PTT Methode CAT "
                                             "(das Programm liest die Leistung über CI-V).")
            return
        if not self.link.rig.is_open:
            for problem in self.link.connect():
                self.log(f"FEHLER: {problem}")
        if not self.link.rig.is_open:
            messagebox.showerror("Sendetest", "RIG COM Port ist nicht verbunden.")
            return
        outputs = audio_devices("out")
        guess = autodetect.guess_by_name(outputs)
        candidates = sorted(outputs, key=lambda n: (n != guess, "USB" not in n.upper()))[:10]
        if not candidates:
            messagebox.showerror("Sendetest", "Keine Soundkarten gefunden (py -m pip install sounddevice?).")
            return
        if not messagebox.askyesno("Sendetest", (
                f"Das Funkgerät sendet jetzt bis zu {len(candidates)}× kurz (je 1 s, 1000 Hz).\n"
                "Antenne/Dummy Load anschließen, wenig Leistung, freie Frequenz im Amateurband.\n"
                "Am PC kann es dabei kurz piepen (das sind die falschen Soundkarten).\n\nStarten?")):
            return
        if self.link.icom_set_usb_data():
            self.log("Hinweis: USB-D konnte nicht gesetzt werden – am Funkgerät DATA-Taste drücken")
        tone = np.frombuffer(bytes(self.audio_gen.generate_sine_wave(1000, 1000, amplitude=0.4)),
                             dtype="<i2").astype(np.float32) / 32768.0
        rate = self.audio_gen.sample_rate

        def _work():
            results = []
            with self.tx_lock:
                for name in candidates:
                    idx = audio_device_index(name, "out")
                    if idx is None:
                        continue
                    if not self.link.set_ptt(True):
                        self.log("Sendetest abgebrochen: PTT geht nicht (siehe oben)")
                        break
                    best = 0
                    try:
                        time.sleep(0.25)
                        sd.play(tone, samplerate=rate, device=idx)
                        for _ in range(3):
                            time.sleep(0.2)
                            best = max(best, self.link.icom_meter("PO") or 0, self.link.icom_meter("ALC") or 0)
                        sd.wait()
                    except Exception as exc:
                        self.log(f"Sendetest {name}: {exc}")
                    finally:
                        self.link.set_ptt(False)
                    self.log(f"Sendetest {name}: Leistung/ALC {best}")
                    results.append((best, name))
                    time.sleep(0.4)
            results.sort(reverse=True)
            winner = results[0][1] if results and results[0][0] > 0 else None

            def _finish():
                if winner is None:
                    messagebox.showwarning("Sendetest", (
                        "Bei keiner Soundkarte kam Leistung heraus.\n\nAm IC-7300 prüfen:\n"
                        "• Betriebsart USB-D (DATA-Taste)\n"
                        "• MENU > SET > Connectors > MOD Input > DATA MOD = USB\n"
                        "• MENU > SET > Connectors > USB MOD Level nicht 0 %\n"
                        "• Icom USB-Treiber installiert, Funkgerät war beim PC-Start eingeschaltet"))
                    return
                inputs = audio_devices("in")
                self.cfg["AUDIO_OUT"] = winner
                partner = autodetect.pick_partner(inputs, winner)
                if partner:
                    self.cfg["AUDIO_IN"] = partner
                try:
                    save_config(self.cfg)
                except OSError:
                    pass
                self.log(f"Funkgeräte-Soundkarte gefunden und gespeichert: {winner}")
                messagebox.showinfo("Sendetest", f"Soundkarte des Funkgeräts:\n{winner}\n\nGespeichert.")
                if done:
                    done(winner, partner)
            self.after(0, _finish)
        threading.Thread(target=_work, daemon=True).start()

    def send_codan(self, kind: str):
        to_id = self.codan_call_id.get().strip().replace(" ", "")
        our_id = str(self.cfg.get("OUR_ID", "")).strip()
        message = self.codan_msg.get().strip()
        name = CODAN_CALLS[kind][2]
        if kind != "hangup" and not (to_id.isdigit() and len(to_id) in (4, 6)):
            messagebox.showerror("CODAN", "Station: 4 oder 6 Ziffern (z.B. 435299).")
            return
        if kind == "page" and not message:
            messagebox.showerror("CODAN", "Bitte eine Nachricht eingeben.")
            return

        if self._codan_uses_cics():
            if kind == "page" and len(message) > 64:
                messagebox.showerror("CODAN", "Nachricht: höchstens 64 Zeichen.")
                return
            command = self.link.codan_command_text(kind, to_id, our_id, message)

            def _work():
                if not self.link.connected:
                    self.log("Nicht verbunden – verbinde …")
                    for problem in self.link.connect():
                        self.log(f"FEHLER: {problem}")
                    self.after(0, self._update_connection_label)
                self.log(f"CODAN {name} an {to_id or '-'} per CICS: {command}")
                problem = self.link.send_codan_cics(command)
                if problem:
                    self.log(f"FEHLER: {problem}")
                    self.after(0, lambda: messagebox.showerror("CODAN", problem))
                else:
                    self.log(f"{name} übergeben – Codan sendet jetzt selbst")
                    self.add_inbox(f"→ {name} gesendet", our_id, to_id, message if kind == "page" else "")
                    if kind == "page":
                        self.after(0, lambda: (self.codan_msg.delete(0, tk.END), self._update_msg_count()))
            threading.Thread(target=_work, daemon=True).start()
            return

        # PC makes the CCIR 493-4 signal
        if kind == "hangup":
            messagebox.showinfo("CODAN", "Auflegen geht nur, wenn der Codan selbst sendet (CICS).")
            return
        if not (our_id.isdigit() and len(our_id) == len(to_id)):
            messagebox.showerror("CODAN", "Eigene ID (Einstellungen) muss gleich viele Ziffern haben wie die "
                                          "gerufene Station (4 oder 6).")
            return
        try:
            preamble = max(0.2, float(self.codan_preamble.get().replace(",", ".")))
        except ValueError:
            preamble = 2.0
        self.cfg["CODAN_PREAMBLE_S"] = preamble
        enc = CodanSelcallEncoder
        fmt = enc.FMT_CHANNEL_TEST if kind == "beacon" else enc.FMT_SELCALL
        category = enc.CATEGORIES.get(self.codan_priority.get(), 100)
        try:
            content = {"page": lambda: enc.page_content(message), "status": lambda: list(enc.STATUS_REQUEST),
                       "gps": lambda: list(enc.GPS_REQUEST)}.get(kind, lambda: [])()
            audio = self.codan_encoder.generate(self.audio_gen, to_id, our_id, fmt=fmt, category=category,
                                                preamble_s=preamble, content=content)
        except ValueError as exc:
            messagebox.showerror("CODAN", str(exc))
            return
        self.add_inbox(f"→ {name} gesendet", our_id, to_id, message.upper() if kind == "page" else "")
        if kind == "page":
            self.codan_msg.delete(0, tk.END)
            self._update_msg_count()
        self.play_audio_with_ptt(self.audio_gen.create_wav_bytes(audio),
                                 f"CODAN {name} {our_id} → {to_id} (CCIR 493-4, Vorspann {preamble:.1f} s)",
                                 listen_after=kind in ("status", "gps", "selcall", "beacon", "page"))

    # ------------------------------------------------------ tone selcall
    def on_mode_change(self, _event):
        mode_cfg = TONE_STANDARDS[self.mode_var.get()]
        for widget in self.keypad_frame.winfo_children():
            widget.destroy()
        if mode_cfg["type"] == "dtmf":
            rows = [["1", "2", "3", "A"], ["4", "5", "6", "B"], ["7", "8", "9", "C"], ["E", "0", "F", "D"]]
            for r, row in enumerate(rows):
                for c, k in enumerate(row):
                    ttk.Button(self.keypad_frame, text=k, width=5,
                               command=lambda key=k: self.append_tone_key(key)).grid(row=r, column=c, padx=5, pady=5)
        else:
            width = 6 if mode_cfg["type"] == "ctcss" else 5
            for idx, k in enumerate(mode_cfg["tones"].keys()):
                ttk.Button(self.keypad_frame, text=k, width=width,
                           command=lambda key=k: self.append_tone_key(key)).grid(
                    row=idx // 4, column=idx % 4, padx=3, pady=3)

    def append_tone_key(self, key):
        if TONE_STANDARDS[self.mode_var.get()]["type"] == "ctcss":
            self.tone_seq_entry.delete(0, tk.END)
        self.tone_seq_entry.insert(tk.END, key)

    def play_tone_seq(self):
        seq = self.tone_seq_entry.get().replace(" ", "").upper()
        if not seq:
            return
        mode_name = self.mode_var.get()
        mode_cfg = TONE_STANDARDS[mode_name]
        dur, gap = mode_cfg["duration"], mode_cfg["gap"]
        audio = bytearray()
        if mode_cfg["type"] == "dtmf":
            for char in seq:
                if char in mode_cfg["matrix"]:
                    audio.extend(self.audio_gen.generate_sine_wave(mode_cfg["matrix"][char], dur))
                    if gap > 0:
                        audio.extend(self.audio_gen.generate_silence(gap))
        elif mode_cfg["type"] == "ctcss":
            if seq in mode_cfg["tones"]:
                audio.extend(self.audio_gen.generate_sine_wave(mode_cfg["tones"][seq], dur))
        else:
            tones, prev = [], None
            for char in seq:
                if char not in mode_cfg["tones"]:
                    continue
                target = "R" if (char == prev and "R" in mode_cfg["tones"]) else char
                tones.append((mode_cfg["tones"][target], dur))
                if gap > 0:
                    tones.append((0, gap))
                prev = target
            audio.extend(self.audio_gen.generate_tone_sequence(tones))
        if audio:
            self.play_audio_with_ptt(self.audio_gen.create_wav_bytes(audio), f"{mode_name} {seq}")

    def send_necode(self):
        call_id = self.necode_call_id.get().strip()
        tones = [(NECODE_TONES[c], 100) for c in call_id if c in NECODE_TONES]
        if tones:
            audio = self.audio_gen.generate_tone_sequence(tones)
            self.play_audio_with_ptt(self.audio_gen.create_wav_bytes(audio), f"Necode {call_id}")

    # ------------------------------------------------------------- RX
    def start_rx_engine(self):
        if not self.decoder_engine.is_running:
            self.toggle_rx_engine()

    def toggle_rx_engine(self):
        if self.decoder_engine.is_running:
            self.decoder_engine.stop()
            self.btn_rx.config(text="RX Decoder Start")
            self.progress_level["value"] = 0
            return
        dev = audio_device_index(self.cfg.get("AUDIO_IN", ""), "in")
        if dev is None and self.cfg.get("AUDIO_IN"):
            self.log(f"Audio-Eingang '{self.cfg.get('AUDIO_IN')}' nicht gefunden")
            return
        if self.decoder_engine.start(dev):
            self.btn_rx.config(text="RX Decoder Stop")
            self.log("RX Decoder läuft (CODAN/CCIR 493-4 und Tonfolgen)")
        else:
            messagebox.showerror("RX", "Audio-Eingang konnte nicht gestartet werden.")

    def on_decoder_event(self, event_type, data):
        if event_type == "get_mode":
            return self.mode_var.get()
        if event_type == "level":
            self.after(0, lambda: self.progress_level.configure(value=min(data * 300, 100)))
        elif event_type == "call":
            call = data
            text = call["text"]
            self.log(f"RX CODAN {call['kind']} von {call['from']} an {call['to']}" + (f": {text}" if text else ""))
            self.add_inbox(call["kind"], call["from"], call["to"], text)
        elif event_type == "char":
            mode, char, rms = data

            def _show():
                self.entry_rx_seq.insert(tk.END, char)
                self.log(f"RX [{mode}] Ton {char} (RMS {rms:.3f})")
            self.after(0, _show)
        return None

    def _quit(self):
        try:
            self.link.set_ptt(False)
        except Exception:
            pass
        self.decoder_engine.stop()
        self.link.disconnect()
        self.destroy()


if __name__ == "__main__":
    SelCallApp().mainloop()
