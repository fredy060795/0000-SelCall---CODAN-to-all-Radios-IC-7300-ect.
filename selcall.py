import math
import struct
import wave
import io
try:
    import winsound
except ImportError:  # not on Windows
    winsound = None
import threading
import time
import json
import os
import serial
import serial.tools.list_ports
import sounddevice as sd
import numpy as np
import tkinter as tk
from tkinter import ttk, messagebox

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")

# Tone Frequency Definitions (in Hz)
TONE_STANDARDS = {
    "DTMF": {
        "type": "dtmf",
        "duration": 100,
        "gap": 50,
        "matrix": {
            "1": (697, 1209), "2": (697, 1336), "3": (697, 1477), "A": (697, 1633),
            "4": (770, 1209), "5": (770, 1336), "6": (770, 1477), "B": (770, 1633),
            "7": (852, 1209), "8": (852, 1336), "9": (852, 1477), "C": (852, 1633),
            "E": (941, 1209), "0": (941, 1336), "F": (941, 1477), "D": (941, 1633)
        }
    },
    "CCIR1": {
        "type": "sequential",
        "duration": 100,
        "gap": 0,
        "tones": {
            "1": 1124, "2": 1197, "3": 1275, "4": 1358, "5": 1446,
            "6": 1540, "7": 1640, "8": 1747, "9": 1860, "0": 1981,
            "A": 2400, "B": 930, "C": 2247, "D": 990, "E": 2110, "R": 2110
        }
    },
    "CCIR7": {
        "type": "sequential",
        "duration": 100,
        "gap": 0,
        "tones": {
            "1": 1124, "2": 1197, "3": 1275, "4": 1358, "5": 1446,
            "6": 1540, "7": 1640, "8": 1747, "9": 1860, "0": 1981,
            "A": 2400, "B": 930, "C": 2247, "D": 990, "E": 2110, "R": 2110
        }
    },
    "PCCIR": {
        "type": "sequential",
        "duration": 100,
        "gap": 0,
        "tones": {
            "1": 1124, "2": 1197, "3": 1275, "4": 1358, "5": 1446,
            "6": 1540, "7": 1640, "8": 1747, "9": 1860, "0": 1981,
            "R": 2110
        }
    },
    "EIA": {
        "type": "sequential",
        "duration": 33,
        "gap": 0,
        "tones": {
            "1": 741, "2": 882, "3": 1023, "4": 1164, "5": 1305,
            "6": 1446, "7": 1587, "8": 1728, "9": 1869, "0": 600,
            "A": 459, "B": 1091, "C": 2010, "D": 2151, "E": 2292, "R": 459
        }
    },
    "EEA": {
        "type": "sequential",
        "duration": 40,
        "gap": 0,
        "tones": {
            "1": 1124, "2": 1197, "3": 1275, "4": 1358, "5": 1446,
            "6": 1540, "7": 1640, "8": 1747, "9": 1860, "0": 1981,
            "A": 1055, "B": 930, "C": 2247, "D": 990, "E": 2110, "R": 2110
        }
    },
    "CCITT": {
        "type": "sequential",
        "duration": 100,
        "gap": 0,
        "tones": {
            "1": 1124, "2": 1197, "3": 1275, "4": 1358, "5": 1446,
            "6": 1540, "7": 1640, "8": 1747, "9": 1860, "0": 1981,
            "A": 2400, "B": 930, "C": 2247, "D": 990, "E": 2110, "R": 2110
        }
    },
    "EURO": {
        "type": "sequential",
        "duration": 100,
        "gap": 0,
        "tones": {
            "1": 979.8, "2": 903.1, "3": 832.5, "4": 767.4, "5": 707.4,
            "6": 652.3, "7": 601.6, "8": 554.9, "9": 511.8, "0": 1062.9
        }
    },
    "NATEL": {
        "type": "sequential",
        "duration": 100,
        "gap": 0,
        "tones": {
            "1": 1633, "2": 1633, "3": 1633, "4": 1633, "5": 1633,
            "6": 1633, "7": 1633, "8": 1633, "9": 1633, "0": 1633
        }
    },
    "VDEW": {
        "type": "sequential",
        "duration": 70,
        "gap": 0,
        "tones": {
            "1": 1060, "2": 1160, "3": 1270, "4": 1400, "5": 1530,
            "6": 1670, "7": 1830, "8": 2000, "9": 2200, "0": 2400
        }
    },
    "MODAT": {
        "type": "sequential",
        "duration": 30,
        "gap": 0,
        "tones": {
            "1": 631.0, "2": 741.0, "3": 882.0, "4": 1023.0, "5": 1164.0,
            "6": 1305.0, "7": 1446.0, "8": 1587.0, "9": 1728.0, "0": 600.0,
            "R": 459.0
        }
    },
    "ZVEI1": {
        "type": "sequential",
        "duration": 70,
        "gap": 0,
        "tones": {
            "1": 1060, "2": 1160, "3": 1270, "4": 1400, "5": 1530,
            "6": 1670, "7": 1830, "8": 2000, "9": 2200, "0": 2400,
            "A": 2800, "B": 810, "C": 930, "D": 885, "E": 2600, "R": 2600
        }
    },
    "ZVEI2": {
        "type": "sequential",
        "duration": 70,
        "gap": 0,
        "tones": {
            "1": 1060, "2": 1160, "3": 1270, "4": 1400, "5": 1530,
            "6": 1670, "7": 1830, "8": 2000, "9": 2200, "0": 2400,
            "A": 885, "B": 810, "C": 930, "D": 1000, "E": 2600, "R": 2600
        }
    },
    "ZVEI3": {
        "type": "sequential",
        "duration": 70,
        "gap": 0,
        "tones": {
            "1": 970, "2": 1060, "3": 1160, "4": 1270, "5": 1400,
            "6": 1530, "7": 1670, "8": 1830, "9": 2000, "0": 2200,
            "A": 885, "B": 810, "C": 930, "D": 2400, "E": 2600, "R": 2600
        }
    },
    "PZVEI": {
        "type": "sequential",
        "duration": 70,
        "gap": 0,
        "tones": {
            "1": 1060, "2": 1160, "3": 1270, "4": 1400, "5": 1530,
            "6": 1670, "7": 1830, "8": 2000, "9": 2200, "0": 2400,
            "R": 2600
        }
    },
    "DZVEI": {
        "type": "sequential",
        "duration": 70,
        "gap": 0,
        "tones": {
            "1": 970, "2": 1060, "3": 1160, "4": 1270, "5": 1400,
            "6": 1530, "7": 1670, "8": 1830, "9": 2000, "0": 2200,
            "R": 2600
        }
    },
    "PDZVEI": {
        "type": "sequential",
        "duration": 70,
        "gap": 0,
        "tones": {
            "1": 970, "2": 1060, "3": 1160, "4": 1270, "5": 1400,
            "6": 1530, "7": 1670, "8": 1830, "9": 2000, "0": 2200,
            "R": 2600
        }
    },
    "ICAO": {
        "type": "icao",
        "duration": 1000,
        "gap": 200,
        "tones": {
            "A": 312.6, "B": 346.7, "C": 384.6, "D": 426.6,
            "E": 473.2, "F": 524.8, "G": 582.1, "H": 645.7,
            "J": 716.1, "K": 794.3, "L": 881.0, "M": 977.2,
            "P": 1083.9, "Q": 1202.3, "R": 1333.5, "S": 1479.1
        }
    },
    "CTCSS": {
        "type": "ctcss",
        "duration": 1000,
        "gap": 0,
        "tones": {
            "67.0": 67.0, "71.9": 71.9, "74.4": 74.4, "77.0": 77.0,
            "79.7": 79.7, "82.5": 82.5, "85.4": 85.4, "88.5": 88.5,
            "91.5": 91.5, "94.8": 94.8, "97.4": 97.4, "100.0": 100.0,
            "103.5": 103.5, "107.2": 107.2, "110.9": 110.9, "114.8": 114.8,
            "118.8": 118.8, "123.0": 123.0, "127.3": 127.3, "131.8": 131.8,
            "136.5": 136.5, "141.3": 141.3, "146.2": 146.2, "151.4": 151.4,
            "156.7": 156.7, "162.2": 162.2, "167.9": 167.9, "173.8": 173.8,
            "179.9": 179.9, "186.2": 186.2, "192.8": 192.8, "203.5": 203.5,
            "210.7": 210.7, "218.1": 218.1, "225.7": 225.7, "233.6": 233.6,
            "241.8": 241.8, "250.3": 250.3, "254.1": 254.1
        }
    }
}

NECODE_TONES = {
    "0": 600, "1": 741, "2": 882, "3": 1023, "4": 1164,
    "5": 1305, "6": 1446, "7": 1587, "8": 1728, "9": 1869
}


class AudioGenerator:
    def __init__(self, sample_rate=48000):
        self.sample_rate = sample_rate

    @staticmethod
    def _to_pcm(signal):
        signal = np.clip(signal, -1.0, 1.0)
        return bytearray((signal * 32767).astype('<i2').tobytes())

    def _ramp(self, signal, ramp_ms=3):
        n = min(int(self.sample_rate * ramp_ms / 1000.0), len(signal) // 2)
        if n > 0:
            ramp = np.linspace(0.0, 1.0, n)
            signal[:n] *= ramp
            signal[-n:] *= ramp[::-1]
        return signal

    def generate_sine_wave(self, frequencies, duration_ms, amplitude=0.5):
        num_samples = int(self.sample_rate * (duration_ms / 1000.0))
        if isinstance(frequencies, (int, float)):
            freqs = [frequencies]
        else:
            freqs = list(frequencies)
        t = np.arange(num_samples) / self.sample_rate
        val = np.zeros(num_samples)
        for f in freqs:
            if f > 0:
                val += np.sin(2.0 * np.pi * f * t)
        val = (val / max(len(freqs), 1)) * amplitude
        return self._to_pcm(self._ramp(val))

    def generate_tone_sequence(self, tones, amplitude=0.5):
        """Phase-continuous sequence of single tones: list of (freq_hz, duration_ms)."""
        freq_per_sample = []
        for freq, dur in tones:
            n = int(round(self.sample_rate * dur / 1000.0))
            freq_per_sample.append(np.full(n, float(freq)))
        if not freq_per_sample:
            return bytearray()
        f = np.concatenate(freq_per_sample)
        phase = 2.0 * np.pi * np.cumsum(f) / self.sample_rate
        signal = np.where(f > 0, np.sin(phase), 0.0) * amplitude
        return self._to_pcm(self._ramp(signal, 5))

    def generate_fsk(self, bits, baud, f_zero, f_one, amplitude=0.5):
        """Phase-continuous 2-FSK (no clicks between bits)."""
        bit_ms = 1000.0 / baud
        # exact sample positions avoid timing drift over long preambles
        bounds = np.round(np.arange(len(bits) + 1) * self.sample_rate / baud).astype(int)
        f = np.empty(bounds[-1])
        for i, b in enumerate(bits):
            f[bounds[i]:bounds[i + 1]] = f_one if b else f_zero
        phase = 2.0 * np.pi * np.cumsum(f) / self.sample_rate
        return self._to_pcm(self._ramp(np.sin(phase) * amplitude, 5))

    def generate_silence(self, duration_ms):
        num_samples = int(self.sample_rate * (duration_ms / 1000.0))
        return bytearray(num_samples * 2)

    def create_wav_bytes(self, audio_data):
        byte_io = io.BytesIO()
        with wave.open(byte_io, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(audio_data)
        return byte_io.getvalue()


class CodanSelcallEncoder:
    """CODAN HF selcall = CCIR 493-4 (4-digit addresses).

    100 baud phase-continuous 2-FSK, 1700 Hz = bit 0, 1870 Hz = bit 1
    (audio frequencies in USB). Each word = 7 information bits (LSB first)
    followed by 3 check bits = number of zero bits in the information part
    (MSB first). Every message word is sent twice (DX / RX, time diversity).
    """
    BAUD = 100
    F_ZERO = 1700.0
    F_ONE = 1870.0

    FMT_SELCALL = 120       # selective call to individual station
    FMT_CHANNEL_TEST = 123  # Codan channel test / beacon (radio answers with tones)
    EOS_ARQ = 117           # end of sequence, acknowledge request
    PHASING_DX = 125
    PHASING_RX = [109, 108, 107, 106, 105, 104]

    CATEGORIES = {
        "Routine": 100,
        "Business": 106,
        "Safety": 108,
        "Urgent": 110,
        "Distress": 112,
    }

    @staticmethod
    def word_bits(value):
        value &= 0x7F
        bits = [(value >> i) & 1 for i in range(7)]
        zeros = bits.count(0)
        bits += [(zeros >> 2) & 1, (zeros >> 1) & 1, zeros & 1]
        return bits

    @staticmethod
    def split_id(station_id, label):
        sid = str(station_id).strip()
        if not (sid.isdigit() and len(sid) == 4):
            raise ValueError(
                f"{label} '{sid}' is invalid: CODAN / CCIR 493-4 selcall uses exactly 4 digits (0000-9999)."
            )
        return int(sid[:2]), int(sid[2:])

    def build_words(self, call_id, our_id, fmt=FMT_SELCALL, category=100):
        b1, b2 = self.split_id(call_id, "Call ID")
        a1, a2 = self.split_id(our_id, "Our ID")
        words = []
        for rx in self.PHASING_RX:
            words += [self.PHASING_DX, rx]
        # DX/RX interleaved, RX copy lags DX copy by 4 words
        words += [
            fmt, fmt,
            b1, fmt,
            b2, fmt,
            category, b1,
            a1, b2,
            a2, category,
            self.EOS_ARQ, a1,
            self.EOS_ARQ, a2,
            self.EOS_ARQ, self.EOS_ARQ,
        ]
        return words

    def build_bits(self, call_id, our_id, fmt=FMT_SELCALL, category=100, preamble_s=2.0):
        n_pre = max(20, int(round(preamble_s * self.BAUD)))
        bits = [i & 1 for i in range(n_pre)]  # dot pattern 0101...
        for w in self.build_words(call_id, our_id, fmt, category):
            bits += self.word_bits(w)
        return bits

    def generate(self, audio_gen, call_id, our_id, fmt=FMT_SELCALL, category=100, preamble_s=2.0):
        bits = self.build_bits(call_id, our_id, fmt, category, preamble_s)
        return audio_gen.generate_fsk(bits, self.BAUD, self.F_ZERO, self.F_ONE)


class AudioDecoderEngine:
    def __init__(self, app_callback, sample_rate=44100, block_size=2048):
        self.app_callback = app_callback
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.stream = None
        self.is_running = False
        self.last_char = None
        self.last_time = 0

    def start(self, device_id):
        self.stop()
        try:
            self.is_running = True
            self.stream = sd.InputStream(
                device=device_id,
                channels=1,
                samplerate=self.sample_rate,
                blocksize=self.block_size,
                callback=self._audio_callback
            )
            self.stream.start()
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
        rms = float(np.sqrt(np.mean(signal_data**2)))
        self.app_callback("level", rms)

        if rms < 0.02:
            return

        fft_data = np.abs(np.fft.rfft(signal_data * np.hanning(len(signal_data))))
        freqs = np.fft.rfftfreq(len(signal_data), 1.0 / self.sample_rate)

        peak_idx = np.argmax(fft_data)
        peak_freq = float(freqs[peak_idx])

        detected_char = None
        current_mode = self.app_callback("get_mode", None)
        mode_cfg = TONE_STANDARDS.get(current_mode, {})

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


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Settings - CAT & Audio Configuration")
        self.geometry("560x540")
        self.parent = parent
        self.resizable(False, False)

        self.in_dev_map = {}
        self.out_dev_map = {}

        self.build_ui()

    def build_ui(self):
        id_frame = ttk.LabelFrame(self, text="Station Identification", padding=10)
        id_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(id_frame, text="Self ID / Our ID:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.entry_our_id = ttk.Entry(id_frame, width=15)
        self.entry_our_id.insert(0, str(self.parent.selected_our_id))
        self.entry_our_id.grid(row=0, column=1, sticky=tk.W, padx=5, pady=5)

        ser_frame = ttk.LabelFrame(self, text="Serial / Modem / Radio Interface", padding=10)
        ser_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(ser_frame, text="COM Port:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.combo_ports = ttk.Combobox(ser_frame, width=12, state="readonly")
        self.combo_ports.grid(row=0, column=1, padx=5, pady=5)

        btn_refresh = ttk.Button(ser_frame, text="Refresh", command=self.refresh_all)
        btn_refresh.grid(row=0, column=2, padx=5, pady=5)

        self.btn_toggle_conn = ttk.Button(
            ser_frame,
            text="Disconnect" if (self.parent.ser and self.parent.ser.is_open) else "Connect",
            command=self.toggle_serial_connection
        )
        self.btn_toggle_conn.grid(row=0, column=3, padx=5, pady=5)

        ttk.Label(ser_frame, text="Baudrate:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.combo_baud = ttk.Combobox(ser_frame, values=["115200", "57600", "38400", "19200", "9600", "4800"], width=12, state="readonly")
        self.combo_baud.set(str(self.parent.selected_baud))
        self.combo_baud.grid(row=1, column=1, padx=5, pady=5)

        ttk.Label(ser_frame, text="PTT Control:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
        self.combo_ptt_mode = ttk.Combobox(
            ser_frame,
            values=[
                "CI-V & RTS/DTR (Icom IC-7300)",
                "Yaesu CAT (TX1; / TX0;)",
                "Codan Envoy / NGT (CICS PTT ON/OFF)",
                "Codan RTS/DTR Hardware PTT",
                "Pactor Modem RTS/DTR",
                "Pactor Modem Command (PTT 1 / PTT 0)"
            ],
            width=32, state="readonly"
        )
        self.combo_ptt_mode.set(self.parent.selected_ptt_mode)
        self.combo_ptt_mode.grid(row=2, column=1, columnspan=3, sticky=tk.W, padx=5, pady=5)

        ttk.Label(ser_frame, text="CI-V Address (hex):").grid(row=3, column=0, sticky=tk.W, padx=5, pady=5)
        self.entry_civ = ttk.Entry(ser_frame, width=6)
        self.entry_civ.insert(0, self.parent.selected_civ_address)
        self.entry_civ.grid(row=3, column=1, sticky=tk.W, padx=5, pady=5)
        ttk.Label(ser_frame, text="IC-7300 = 94, IC-7610 = 98, IC-705 = A4").grid(
            row=3, column=2, columnspan=2, sticky=tk.W, padx=5, pady=5)

        audio_frame = ttk.LabelFrame(self, text="Audio Devices Configuration", padding=10)
        audio_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(audio_frame, text="Input (Listen):").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.combo_audio_in = ttk.Combobox(audio_frame, width=35, state="readonly")
        self.combo_audio_in.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(audio_frame, text="Output (TX):").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.combo_audio_out = ttk.Combobox(audio_frame, width=35, state="readonly")
        self.combo_audio_out.grid(row=1, column=1, padx=5, pady=5)

        btn_frame = ttk.Frame(self, padding=10)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)

        btn_save = ttk.Button(btn_frame, text="Save", command=self.save_settings)
        btn_save.pack(side=tk.RIGHT, padx=5)

        btn_cancel = ttk.Button(btn_frame, text="Cancel", command=self.destroy)
        btn_cancel.pack(side=tk.RIGHT, padx=5)

        self.refresh_all()

    def refresh_all(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.combo_ports['values'] = ports
        if ports:
            if self.parent.selected_port in ports:
                self.combo_ports.set(self.parent.selected_port)
            else:
                self.combo_ports.current(0)

        devices = sd.query_devices()
        in_devs = []
        out_devs = []
        self.in_dev_map = {}
        self.out_dev_map = {}

        for i, dev in enumerate(devices):
            name = f"{i}: {dev['name']}"
            if dev['max_input_channels'] > 0:
                in_devs.append(name)
                self.in_dev_map[name] = i
            if dev['max_output_channels'] > 0:
                out_devs.append(name)
                self.out_dev_map[name] = i

        self.combo_audio_in['values'] = in_devs
        self.combo_audio_out['values'] = out_devs

        if in_devs:
            curr_in_name = next((k for k, v in self.in_dev_map.items() if v == self.parent.selected_audio_in), in_devs[0])
            self.combo_audio_in.set(curr_in_name)
        if out_devs:
            curr_out_name = next((k for k, v in self.out_dev_map.items() if v == self.parent.selected_audio_out), out_devs[0])
            self.combo_audio_out.set(curr_out_name)

    def toggle_serial_connection(self):
        if self.parent.ser and self.parent.ser.is_open:
            self.parent.disconnect_serial()
            self.btn_toggle_conn.config(text="Connect")
        else:
            port = self.combo_ports.get()
            baud = int(self.combo_baud.get())
            if not port:
                messagebox.showerror("Error", "No COM port selected.")
                return
            if self.parent.connect_serial(port, baud):
                self.btn_toggle_conn.config(text="Disconnect")

    def save_settings(self):
        port = self.combo_ports.get()
        baud = int(self.combo_baud.get())
        ptt_mode = self.combo_ptt_mode.get()
        in_name = self.combo_audio_in.get()
        out_name = self.combo_audio_out.get()
        our_id = self.entry_our_id.get().strip()

        civ = self.entry_civ.get().strip().upper() or "94"
        try:
            int(civ, 16)
        except ValueError:
            messagebox.showerror("Error", "CI-V address must be hexadecimal, e.g. 94.")
            return

        port_changed = (port != self.parent.selected_port or baud != self.parent.selected_baud)
        self.parent.selected_port = port
        self.parent.selected_baud = baud
        self.parent.selected_ptt_mode = ptt_mode
        self.parent.selected_our_id = our_id
        self.parent.selected_civ_address = civ

        if port and (port_changed or not (self.parent.ser and self.parent.ser.is_open)):
            self.parent.connect_serial(port, baud)

        if hasattr(self.parent, 'codan_our_id'):
            self.parent.codan_our_id.delete(0, tk.END)
            self.parent.codan_our_id.insert(0, our_id)

        if in_name in self.in_dev_map:
            self.parent.selected_audio_in = self.in_dev_map[in_name]
        if out_name in self.out_dev_map:
            self.parent.selected_audio_out = self.out_dev_map[out_name]

        self.parent.save_config_file()
        self.parent.restart_rx_engine()

        messagebox.showinfo("Success", "Settings saved successfully.")
        self.destroy()


class SelCallApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SelCall Terminal")
        self.geometry("560x680")
        self.ser = None

        self.selected_port = ""
        self.selected_baud = 115200
        self.selected_ptt_mode = "CI-V & RTS/DTR (Icom IC-7300)"
        self.selected_our_id = "5678"
        self.selected_audio_in = None
        self.selected_audio_out = None
        self.selected_audio_in_name = ""
        self.selected_audio_out_name = ""
        self.selected_codan_preamble = 2.0
        self.selected_civ_address = "94"

        self.load_config_file()
        self.resolve_audio_devices()

        self.audio_gen = AudioGenerator()
        self.codan_encoder = CodanSelcallEncoder()
        self.tx_lock = threading.Lock()
        self.decoder_engine = AudioDecoderEngine(self.on_decoder_event)

        self.create_menu()
        self.create_rx_panel()
        self.create_tabs()
        self.create_footer()

        if self.selected_port:
            self.after(300, lambda: self.connect_serial(self.selected_port, self.selected_baud, quiet=True))

    def load_config_file(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    self.selected_port = cfg.get("port", "")
                    self.selected_baud = cfg.get("baud", 115200)
                    self.selected_ptt_mode = cfg.get("ptt_mode", "CI-V & RTS/DTR (Icom IC-7300)")
                    self.selected_our_id = cfg.get("our_id", "5678")
                    self.selected_audio_in = cfg.get("audio_in", None)
                    self.selected_audio_out = cfg.get("audio_out", None)
                    self.selected_audio_in_name = cfg.get("audio_in_name", "")
                    self.selected_audio_out_name = cfg.get("audio_out_name", "")
                    self.selected_codan_preamble = float(cfg.get("codan_preamble", 2.0))
                    self.selected_civ_address = str(cfg.get("civ_address", "94"))
            except Exception as e:
                print(f"Error loading settings.json: {e}")

    @staticmethod
    def device_name(index):
        if index is None:
            return ""
        try:
            return sd.query_devices(index)['name']
        except Exception:
            return ""

    def resolve_audio_devices(self):
        """Device indices change when USB devices are re-plugged: prefer the saved name."""
        try:
            devices = sd.query_devices()
        except Exception:
            return
        for attr, kind in (("selected_audio_in", "max_input_channels"),
                           ("selected_audio_out", "max_output_channels")):
            name = getattr(self, attr + "_name")
            if not name:
                continue
            idx = getattr(self, attr)
            if idx is not None and 0 <= idx < len(devices) and devices[idx]['name'] == name:
                continue
            for i, dev in enumerate(devices):
                if dev['name'] == name and dev[kind] > 0:
                    setattr(self, attr, i)
                    break

    def save_config_file(self):
        cfg = {
            "port": self.selected_port,
            "baud": self.selected_baud,
            "ptt_mode": self.selected_ptt_mode,
            "our_id": self.selected_our_id,
            "audio_in": self.selected_audio_in,
            "audio_out": self.selected_audio_out,
            "audio_in_name": self.device_name(self.selected_audio_in),
            "audio_out_name": self.device_name(self.selected_audio_out),
            "codan_preamble": self.selected_codan_preamble,
            "civ_address": self.selected_civ_address
        }
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4)
        except Exception as e:
            print(f"Error saving settings.json: {e}")

    def create_menu(self):
        menu_bar = tk.Menu(self)
        file_menu = tk.Menu(menu_bar, tearoff=0)
        file_menu.add_command(label="Exit", command=self.quit)
        menu_bar.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menu_bar, tearoff=0)
        edit_menu.add_command(label="Settings", command=self.open_settings)
        menu_bar.add_cascade(label="Edit", menu=edit_menu)

        self.config(menu=menu_bar)

    def create_rx_panel(self):
        rx_frame = ttk.LabelFrame(self, text="Receiver / RX SelCall Decoder", padding=10)
        rx_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(rx_frame, text="Signal Level:").grid(row=0, column=0, sticky=tk.W, padx=5)
        self.progress_level = ttk.Progressbar(rx_frame, length=120, mode='determinate')
        self.progress_level.grid(row=0, column=1, padx=5)

        self.btn_rx_toggle = ttk.Button(rx_frame, text="Start RX", command=self.toggle_rx_engine)
        self.btn_rx_toggle.grid(row=0, column=2, padx=5)

        btn_clear_rx = ttk.Button(rx_frame, text="Clear RX Log", command=self.clear_rx_log)
        btn_clear_rx.grid(row=0, column=3, padx=5)

        ttk.Label(rx_frame, text="Decoded Sequence:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.entry_rx_seq = ttk.Entry(rx_frame, width=25)
        self.entry_rx_seq.grid(row=1, column=1, columnspan=2, sticky=tk.W, padx=5, pady=5)

        self.txt_rx_log = tk.Text(rx_frame, height=4, width=55, state="disabled")
        self.txt_rx_log.grid(row=2, column=0, columnspan=4, padx=5, pady=5)

    def log(self, text):
        def _do():
            timestamp = time.strftime("%H:%M:%S")
            self.txt_rx_log.config(state="normal")
            self.txt_rx_log.insert(tk.END, f"[{timestamp}] {text}\n")
            self.txt_rx_log.see(tk.END)
            self.txt_rx_log.config(state="disabled")
        self.after(0, _do)

    def clear_rx_log(self):
        self.entry_rx_seq.delete(0, tk.END)
        self.txt_rx_log.config(state="normal")
        self.txt_rx_log.delete("1.0", tk.END)
        self.txt_rx_log.config(state="disabled")

    def toggle_rx_engine(self):
        if self.decoder_engine.is_running:
            self.decoder_engine.stop()
            self.btn_rx_toggle.config(text="Start RX")
            self.progress_level['value'] = 0
        else:
            if self.selected_audio_in is not None:
                if self.decoder_engine.start(self.selected_audio_in):
                    self.btn_rx_toggle.config(text="Stop RX")
                else:
                    messagebox.showerror("RX Error", "Could not start audio input stream.")
            else:
                messagebox.showwarning("Settings Warning", "Please select an Input (Listen) audio device in Settings.")

    def restart_rx_engine(self):
        if self.decoder_engine.is_running:
            self.toggle_rx_engine()
            self.toggle_rx_engine()

    def on_decoder_event(self, event_type, data):
        if event_type == "level":
            scaled_val = min(data * 300, 100)
            self.progress_level['value'] = scaled_val
        elif event_type == "get_mode":
            return self.mode_var.get()
        elif event_type == "char":
            mode, char, rms = data
            self.entry_rx_seq.insert(tk.END, char)

            timestamp = time.strftime("%H:%M:%S")
            log_line = f"[{timestamp}] [{mode}] Tone: {char} (RMS: {rms:.3f})\n"

            self.txt_rx_log.config(state="normal")
            self.txt_rx_log.insert(tk.END, log_line)
            self.txt_rx_log.see(tk.END)
            self.txt_rx_log.config(state="disabled")

    def open_settings(self):
        SettingsDialog(self)

    def connect_serial(self, port, baud, quiet=False):
        if self.ser and self.ser.is_open:
            self.ser.close()
        try:
            ser = serial.Serial()
            ser.port = port
            ser.baudrate = baud
            ser.timeout = 0.1
            ser.write_timeout = 1
            # pyserial raises DTR/RTS on open by default -> radio could key up
            ser.dtr = False
            ser.rts = False
            ser.open()
            self.ser = ser
            self.log(f"Serial {port} @ {baud} connected ({self.selected_ptt_mode})")
            return True
        except Exception as e:
            self.ser = None
            self.log(f"Serial {port} could not be opened: {e}")
            if not quiet:
                messagebox.showerror("Serial Error", f"Could not open {port}: {e}")
            return False

    def disconnect_serial(self):
        if self.ser and self.ser.is_open:
            try:
                self.ser.dtr = False
                self.ser.rts = False
            except Exception:
                pass
            self.ser.close()
        self.ser = None

    def ensure_serial(self):
        if self.ser and self.ser.is_open:
            return True
        if self.selected_port:
            return self.connect_serial(self.selected_port, self.selected_baud, quiet=True)
        return False

    def civ_frame(self, payload: bytes) -> bytes:
        try:
            addr = int(self.selected_civ_address, 16) & 0xFF
        except ValueError:
            addr = 0x94
        return b'\xFE\xFE' + bytes([addr, 0xE0]) + payload + b'\xFD'

    def set_ptt(self, active: bool) -> bool:
        if not (self.ser and self.ser.is_open):
            return False
        try:
            mode = self.selected_ptt_mode

            # 1. Icom CI-V (cmd 1C 00: 01 = TX, 00 = RX) + USB SEND via RTS/DTR
            if mode == "CI-V & RTS/DTR (Icom IC-7300)":
                self.ser.write(self.civ_frame(b'\x1C\x00' + (b'\x01' if active else b'\x00')))
                self.ser.rts = active
                self.ser.dtr = active

            # 2. Yaesu CAT Standard (TX1; / TX0;)
            elif mode == "Yaesu CAT (TX1; / TX0;)":
                self.ser.write(b"TX1;" if active else b"TX0;")
                self.ser.rts = active
                self.ser.dtr = active

            # 3. Codan Envoy / NGT (CICS Interface Command System)
            elif mode == "Codan Envoy / NGT (CICS PTT ON/OFF)":
                self.ser.write(b"PTT ON\r\n" if active else b"PTT OFF\r\n")
                self.ser.rts = active

            # 4./5. Hardware RTS/DTR keying (Codan RFU/console, Pactor modem, interfaces)
            elif mode in ("Codan RTS/DTR Hardware PTT", "Pactor Modem RTS/DTR"):
                self.ser.rts = active
                self.ser.dtr = active

            # 6. Pactor / Modem ASCII Command Mode
            elif mode == "Pactor Modem Command (PTT 1 / PTT 0)":
                self.ser.write(b"PTT 1\r\n" if active else b"PTT 0\r\n")
                self.ser.rts = active

            self.ser.flush()
            return True
        except Exception as e:
            self.log(f"PTT error: {e}")
            return False

    def play_audio_with_ptt(self, wav_bytes):
        if not self.tx_lock.acquire(blocking=False):
            self.log("TX busy - wait until the current transmission is finished")
            return

        if not self.ensure_serial():
            self.log("WARNING: no serial/CAT connection - PTT is NOT keyed (audio only)")
        if self.selected_audio_out is None:
            self.log("WARNING: no TX audio device selected - using Windows default output")

        rx_was_running = self.decoder_engine.is_running

        def _play():
            try:
                if rx_was_running:
                    self.decoder_engine.stop()
                keyed = self.set_ptt(True)
                if keyed:
                    self.log("PTT ON")
                time.sleep(0.3)  # let the transmitter / ALC settle

                wav_io = io.BytesIO(wav_bytes)
                with wave.open(wav_io, 'rb') as wf:
                    data = wf.readframes(wf.getnframes())
                    rate = wf.getframerate()
                samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                try:
                    sd.play(samples, samplerate=rate, device=self.selected_audio_out, blocking=True)
                except Exception as e:
                    self.log(f"Audio output error ({e}) - falling back to default device")
                    if winsound is not None:
                        winsound.PlaySound(wav_bytes, winsound.SND_MEMORY)
                    else:
                        sd.play(samples, samplerate=rate, blocking=True)

                time.sleep(0.15)
            finally:
                if self.set_ptt(False):
                    self.log("PTT OFF")
                if rx_was_running:
                    self.after(0, lambda: self.decoder_engine.start(self.selected_audio_in))
                self.tx_lock.release()

        threading.Thread(target=_play, daemon=True).start()

    def create_tabs(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 0))

        self.tab_tone = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_tone, text="Tone SelCall")
        self.build_tone_tab()

        self.tab_codan = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_codan, text="CODAN")
        self.build_codan_tab()

        self.tab_necode = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_necode, text="Necode")
        self.build_necode_tab()

    def create_footer(self):
        footer_frame = ttk.Frame(self, padding=(10, 5))
        footer_frame.pack(fill=tk.X, side=tk.BOTTOM)

        copyright_label = ttk.Label(footer_frame, text="Frederic Tartarone © 2026")
        copyright_label.pack(side=tk.RIGHT)

    def build_tone_tab(self):
        top_frame = ttk.Frame(self.tab_tone, padding=10)
        top_frame.pack(fill=tk.X)

        self.mode_var = tk.StringVar(value="DTMF")
        self.mode_combo = ttk.Combobox(
            top_frame, textvariable=self.mode_var,
            values=list(TONE_STANDARDS.keys()), state="readonly", width=15
        )
        self.mode_combo.pack(anchor=tk.W, pady=5)
        self.mode_combo.bind("<<ComboboxSelected>>", self.on_mode_change)

        seq_frame = ttk.Frame(self.tab_tone, padding=10)
        seq_frame.pack(fill=tk.X)

        self.tone_seq_entry = ttk.Entry(seq_frame, width=25)
        self.tone_seq_entry.insert(0, "1 123 456 7890")
        self.tone_seq_entry.pack(side=tk.LEFT, padx=(0, 10))

        btn_play = ttk.Button(seq_frame, text="Play", command=self.play_tone_seq)
        btn_play.pack(side=tk.LEFT)

        self.keypad_frame = ttk.Frame(self.tab_tone, padding=10)
        self.keypad_frame.pack(fill=tk.BOTH, expand=True)

        self.on_mode_change(None)

    def on_mode_change(self, event):
        mode_name = self.mode_var.get()
        mode_cfg = TONE_STANDARDS[mode_name]

        for widget in self.keypad_frame.winfo_children():
            widget.destroy()

        if mode_cfg["type"] == "dtmf":
            keys = [
                ["1", "2", "3", "A"],
                ["4", "5", "6", "B"],
                ["7", "8", "9", "C"],
                ["E", "0", "F", "D"]
            ]
            for r, row in enumerate(keys):
                for c, k in enumerate(row):
                    btn = ttk.Button(self.keypad_frame, text=k, width=5, command=lambda key=k: self.append_tone_key(key))
                    btn.grid(row=r, column=c, padx=5, pady=5)
        elif mode_cfg["type"] == "ctcss":
            keys = list(mode_cfg["tones"].keys())
            cols = 4
            for idx, k in enumerate(keys):
                r = idx // cols
                c = idx % cols
                btn = ttk.Button(self.keypad_frame, text=k, width=6, command=lambda key=k: self.append_tone_key(key))
                btn.grid(row=r, column=c, padx=2, pady=2)
        else:
            keys = list(mode_cfg["tones"].keys())
            cols = 4
            for idx, k in enumerate(keys):
                r = idx // cols
                c = idx % cols
                btn = ttk.Button(self.keypad_frame, text=k, width=5, command=lambda key=k: self.append_tone_key(key))
                btn.grid(row=r, column=c, padx=5, pady=5)

    def append_tone_key(self, key):
        current = self.tone_seq_entry.get()
        self.tone_seq_entry.delete(0, tk.END)
        self.tone_seq_entry.insert(0, current + key)

    def play_tone_seq(self):
        seq = self.tone_seq_entry.get().replace(" ", "")
        if not seq:
            return

        mode_name = self.mode_var.get()
        mode_cfg = TONE_STANDARDS[mode_name]
        dur = mode_cfg["duration"]
        gap = mode_cfg["gap"]

        combined_audio = bytearray()
        prev_key = None

        if mode_cfg["type"] == "dtmf":
            for char in seq:
                if char in mode_cfg["matrix"]:
                    freqs = mode_cfg["matrix"][char]
                    combined_audio.extend(self.audio_gen.generate_sine_wave(freqs, dur))
                    if gap > 0:
                        combined_audio.extend(self.audio_gen.generate_silence(gap))
        elif mode_cfg["type"] == "ctcss":
            if seq in mode_cfg["tones"]:
                freqs = mode_cfg["tones"][seq]
                combined_audio.extend(self.audio_gen.generate_sine_wave(freqs, dur))
        else:
            tones = []
            for char in seq:
                if char not in mode_cfg["tones"]:
                    continue
                target_char = char
                # repeated digit -> repeat tone (R), e.g. 1 1 1 -> 1 R 1
                if char == prev_key and "R" in mode_cfg["tones"]:
                    target_char = "R"
                tones.append((mode_cfg["tones"][target_char], dur))
                if gap > 0:
                    tones.append((0, gap))
                prev_key = target_char
            combined_audio.extend(self.audio_gen.generate_tone_sequence(tones))

        if combined_audio:
            wav_bytes = self.audio_gen.create_wav_bytes(combined_audio)
            self.play_audio_with_ptt(wav_bytes)

    def build_codan_tab(self):
        btn_frame = ttk.Frame(self.tab_codan, padding=10)
        btn_frame.pack(fill=tk.X)

        self.codan_priority = tk.StringVar(value="Routine")
        for p in CodanSelcallEncoder.CATEGORIES:
            btn = ttk.Radiobutton(btn_frame, text=p, value=p, variable=self.codan_priority, style="Toolbutton")
            btn.pack(side=tk.LEFT, padx=2)

        form_frame = ttk.Frame(self.tab_codan, padding=10)
        form_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(form_frame, text="Call ID (4 digits):").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.codan_call_id = ttk.Entry(form_frame, width=15)
        self.codan_call_id.insert(0, "1234")
        self.codan_call_id.grid(row=0, column=1, sticky=tk.W, padx=10, pady=5)

        ttk.Label(form_frame, text="Our ID (4 digits):").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.codan_our_id = ttk.Entry(form_frame, width=15)
        self.codan_our_id.insert(0, str(self.selected_our_id))
        self.codan_our_id.grid(row=1, column=1, sticky=tk.W, padx=10, pady=5)

        ttk.Label(form_frame, text="Preamble (s):").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.codan_preamble = ttk.Spinbox(form_frame, from_=0.5, to=30, increment=0.5, width=6)
        self.codan_preamble.set(str(self.selected_codan_preamble))
        self.codan_preamble.grid(row=2, column=1, sticky=tk.W, padx=10, pady=5)
        ttk.Label(form_frame, text="2 s = radio on channel, 6-12 s = radio scanning").grid(
            row=2, column=2, sticky=tk.W, pady=5)

        btn_send = ttk.Button(form_frame, text="Send SelCall", command=self.send_codan)
        btn_send.grid(row=3, column=1, sticky=tk.W, padx=10, pady=15)

        btn_test = ttk.Button(form_frame, text="Channel Test", command=self.send_codan_channel_test)
        btn_test.grid(row=3, column=2, sticky=tk.W, padx=5, pady=15)

        ttk.Label(
            form_frame,
            text="CCIR 493-4 / CODAN: 100 Bd FSK 1700/1870 Hz. Radio in USB (IC-7300: USB-D).",
            foreground="gray"
        ).grid(row=4, column=0, columnspan=3, sticky=tk.W, pady=5)

    def _codan_preamble_seconds(self):
        try:
            return max(0.2, float(self.codan_preamble.get().replace(",", ".")))
        except ValueError:
            return 2.0

    def _send_codan_frame(self, fmt):
        call_id = self.codan_call_id.get().strip()
        our_id = self.codan_our_id.get().strip()
        category = CodanSelcallEncoder.CATEGORIES.get(self.codan_priority.get(), 100)
        preamble = self._codan_preamble_seconds()
        try:
            audio = self.codan_encoder.generate(
                self.audio_gen, call_id, our_id, fmt=fmt, category=category, preamble_s=preamble)
        except ValueError as e:
            messagebox.showerror("CODAN SelCall", str(e))
            return
        self.selected_codan_preamble = preamble
        self.log(f"TX CODAN {'Selcall' if fmt == CodanSelcallEncoder.FMT_SELCALL else 'Channel Test'} "
                 f"{our_id} -> {call_id} ({self.codan_priority.get()}, preamble {preamble:.1f} s)")
        self.play_audio_with_ptt(self.audio_gen.create_wav_bytes(audio))

    def send_codan(self):
        self._send_codan_frame(CodanSelcallEncoder.FMT_SELCALL)

    def send_codan_channel_test(self):
        self._send_codan_frame(CodanSelcallEncoder.FMT_CHANNEL_TEST)

    def build_necode_tab(self):
        form_frame = ttk.Frame(self.tab_necode, padding=20)
        form_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(form_frame, text="Call ID:").grid(row=0, column=0, sticky=tk.W, pady=10)
        self.necode_call_id = ttk.Entry(form_frame, width=15)
        self.necode_call_id.insert(0, "1234")
        self.necode_call_id.grid(row=0, column=1, sticky=tk.W, padx=10, pady=10)

        btn_send = ttk.Button(form_frame, text="Send", command=self.send_necode)
        btn_send.grid(row=1, column=1, sticky=tk.W, padx=10, pady=20)

    def send_necode(self):
        call_id = self.necode_call_id.get().strip()
        combined_audio = bytearray()

        for char in call_id:
            if char in NECODE_TONES:
                freq = NECODE_TONES[char]
                combined_audio.extend(self.audio_gen.generate_sine_wave(freq, 100))

        if combined_audio:
            wav_bytes = self.audio_gen.create_wav_bytes(combined_audio)
            self.play_audio_with_ptt(wav_bytes)


if __name__ == "__main__":
    app = SelCallApp()
    app.mainloop()
