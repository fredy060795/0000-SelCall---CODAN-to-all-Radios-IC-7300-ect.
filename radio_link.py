"""Connection to the radio and the PACTOR modem, set up like in HFChat.

Two serial ports, both optional:

  * RIG  (CAT)  - the radio directly on the PC (Icom CI-V, Yaesu, Kenwood,
                  Codan CICS).
  * PTC  (TNC)  - SCS PACTOR modem (PTC-II, DR-7400, DR-7800, DR-9400); the
                  radio hangs on the modem's TRX port.

How a SelCall goes out:

  * Codan radio, CICS:  the radio sends its own Codan selcall.  The program
    only gives the command ("selcall 435299"):
        PTT method CAT -> on the RIG port, ended with CR
        PTT method TNC -> through the modem: "TRX T selcall 435299"
                          (terminal mode, the modem passes the text
                          to the radio, like "TRX T freq 4947.000")
  * Other radio (IC-7300 ...): the PC makes the tones / FSK and plays them on
    the sound card; PTT by CAT command, RTS or DTR on the RIG port, or VOX.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

try:
    import serial
    import serial.tools.list_ports
except ImportError:  # pragma: no cover - checked at start of the GUI
    serial = None


def _crc16_x25(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc ^ 0xFFFF


def _hostmode_frame(payload: bytes, *, crc: bool, counter: bool = False) -> bytes:
    """WA8DED / SCS CRC hostmode command frame on channel 0."""
    code = 0x01 | (0x80 if (crc and counter) else 0x00)
    body = bytes([0, code, len(payload) - 1]) + payload
    if not crc:
        return body
    fcs = _crc16_x25(body)
    data = body + bytes([fcs & 0xFF, fcs >> 8])
    return b"\xAA\xAA" + data.replace(b"\xAA", b"\xAA\x00")


def hostmode_exit_bytes() -> bytes:
    """JHOST0 in every hostmode variant a program (e.g. HFChat) may have left on."""
    return (_hostmode_frame(b"JHOST0", crc=True, counter=False)
            + _hostmode_frame(b"JHOST0", crc=True, counter=True)
            + _hostmode_frame(b"JHOST0", crc=False))

PTT_METHODS = ("CAT", "TNC", "RTS", "DTR", "VOX")
CAT_PROTOCOLS = ("ICOM", "Yaesu", "Kenwood", "CODAN")
PTC_MODEM_TYPES = ("AUTO", "PTC-II", "DR-7400", "DR-7800", "DR-9400")
PTC_BAUD_RATES = (9600, 19200, 38400, 57600, 115200)
RIG_BAUD_RATES = (4800, 9600, 19200, 38400, 57600, 115200)

# Codan CICS call commands (CICS V3: Envoy, NGT, 2110).  {to} = called
# station, {self} = own address, {msg} = message text.  The self address is
# optional: without it the radio uses its own.
DEFAULT_CODAN_SELCALL_CMD = "selcall {to}"
DEFAULT_CODAN_BEACON_CMD = "beacon {to}"
CODAN_CALLS = {
    # kind: (settings key, default command, name in the log)
    "selcall": ("CODAN_SELCALL_CMD", DEFAULT_CODAN_SELCALL_CMD, "Selcall"),
    "page": ("CODAN_PAGE_CMD", 'pagecall {to} "{msg}"', "Nachricht (Pagecall)"),
    "status": ("CODAN_STATUS_CMD", "statuscall {to}", "Status-Abfrage"),
    "gps": ("CODAN_GPS_CMD", "gpscall {to}", "GPS-Abfrage"),
    "beacon": ("CODAN_BEACON_CMD", DEFAULT_CODAN_BEACON_CMD, "Kanaltest"),
    "hangup": ("CODAN_HANGUP_CMD", "hangup", "Auflegen"),
}


def list_serial_ports() -> list:
    if serial is None:
        return []
    return [p.device for p in serial.tools.list_ports.comports()]


class SerialLine:
    """A serial port with a reader thread that hands every text line to `on_line`."""

    def __init__(self, name: str, on_line: Callable[[str, str], None]):
        self.name = name
        self.on_line = on_line
        self.ser = None
        self._stop = threading.Event()
        self._thread = None
        self._buffer = b""
        self._lock = threading.Lock()
        self._recent = []          # (time, text) of the last answers
        self.port = ""
        self.baud = 0

    @property
    def is_open(self) -> bool:
        return self.ser is not None and self.ser.is_open

    def open(self, port: str, baud: int, *, rtscts: bool = False):
        self.close()
        if serial is None:
            raise RuntimeError("pyserial ist nicht installiert (py -m pip install pyserial)")
        ser = serial.Serial()
        ser.port = port
        ser.baudrate = int(baud)
        ser.timeout = 0.1
        ser.write_timeout = 2
        ser.rtscts = rtscts
        # pyserial raises DTR/RTS on open -> a radio with USB SEND = DTR/RTS
        # would key up and stay in TX.
        ser.dtr = False
        ser.rts = False
        ser.open()
        self.ser = ser
        self.port, self.baud = port, int(baud)
        self._stop.clear()
        self._thread = threading.Thread(target=self._reader, name=f"{self.name}-reader", daemon=True)
        self._thread.start()

    def close(self):
        self._stop.set()
        ser, self.ser = self.ser, None
        if ser is not None:
            try:
                ser.dtr = False
                ser.rts = False
            except Exception:
                pass
            try:
                ser.close()
            except Exception:
                pass
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
        self._thread = None

    def write(self, data: bytes) -> bool:
        if not self.is_open:
            return False
        with self._lock:
            self.ser.write(data)
            self.ser.flush()
        return True

    def set_lines(self, *, rts: Optional[bool] = None, dtr: Optional[bool] = None):
        if not self.is_open:
            return
        if rts is not None:
            self.ser.rts = rts
        if dtr is not None:
            self.ser.dtr = dtr

    def clear_recent(self):
        self._recent = []

    def wait_for(self, predicate: Callable[[str], bool], timeout: float) -> Optional[str]:
        """First line (or prompt) received after clear_recent() that matches."""
        end = time.time() + timeout
        seen = 0
        while time.time() < end:
            lines = list(self._recent)
            for _, text in lines[seen:]:
                if predicate(text):
                    return text
            seen = len(lines)
            time.sleep(0.05)
        return None

    def _reader(self):
        while not self._stop.is_set():
            ser = self.ser
            if ser is None:
                break
            try:
                data = ser.read(256)
            except Exception as exc:
                self.on_line(self.name, f"Lesefehler: {exc}")
                break
            if not data:
                # a prompt without line end ("cmd: ") still counts
                if self._buffer.strip():
                    self._emit(self._buffer)
                    self._buffer = b""
                continue
            self._buffer += data
            while True:
                cut = min((i for i in (self._buffer.find(b"\r"), self._buffer.find(b"\n")) if i >= 0), default=-1)
                if cut < 0:
                    break
                line, self._buffer = self._buffer[:cut], self._buffer[cut + 1:]
                self._emit(line)

    def _emit(self, raw: bytes):
        # hostmode frames or CI-V binary: show as hex, text as text
        if any(b < 0x20 and b not in (9,) for b in raw) or any(b >= 0x80 for b in raw):
            text = raw.hex(" ").upper()
        else:
            text = raw.decode("ascii", errors="replace").strip()
        if not text:
            return
        self._recent.append((time.time(), text))
        if len(self._recent) > 200:
            self._recent = self._recent[-100:]
        self.on_line(self.name, text)


class RadioLink:
    """RIG and PTC port plus everything that keys or commands the radio."""

    def __init__(self, cfg: dict, log: Callable[[str], None], profile_lookup: Callable[[str], object]):
        self.cfg = cfg
        self.log = log
        self.profile_lookup = profile_lookup
        self.rig = SerialLine("RIG", self._on_line)
        self.ptc = SerialLine("PTC", self._on_line)
        self.detected_modem = ""
        self._modem_trx_setup_for = ""

    # ------------------------------------------------------------------ setup
    on_radio_line = None      # app hook: every text line from radio/modem

    def remember_sent(self, text: str):
        recent = getattr(self, "_sent", [])
        recent.append(text.strip().lower())
        self._sent = recent[-20:]

    def is_echo(self, text: str) -> bool:
        """True for the radio's/modem's echo of a command we sent, or a bare prompt."""
        t = text.strip().lower()
        if t.startswith("cmd:"):
            t = t[4:].strip()
        if not t:
            return True
        return any(t == sent or t == f"trx t {sent}" or t.endswith(sent) and len(t) - len(sent) <= 6
                   for sent in getattr(self, "_sent", []))

    def _on_line(self, port: str, text: str):
        self.log(f"{port} → {text}")
        if self.on_radio_line is not None:
            try:
                self.on_radio_line(port, text)
            except Exception:
                pass
        upper = text.upper()
        for modem in ("DR-9400", "DR-7800", "DR-7400", "PTC-IIIUSB", "PTC-II"):
            if port == "PTC" and modem in upper and not self.detected_modem:
                self.detected_modem = "PTC-II" if modem.startswith("PTC") else modem
                self.log(f"Modem erkannt: {self.detected_modem}")

    @property
    def ptt_method(self) -> str:
        return str(self.cfg.get("PTT_METHOD", "CAT") or "CAT").upper()

    @property
    def profile(self):
        return self.profile_lookup(self.cfg.get("RADIO_MODEL", ""))

    @property
    def cat_protocol(self) -> str:
        proto = str(self.cfg.get("CAT_PROTOCOL", "ICOM") or "ICOM")
        return {"YAESU": "Yaesu", "KENWOOD": "Kenwood"}.get(proto.upper(), proto.upper() if proto.upper() in ("ICOM", "CODAN") else proto)

    @property
    def is_codan(self) -> bool:
        profile = self.profile
        if profile is not None:
            return bool(profile.is_codan)
        return self.cat_protocol == "CODAN"

    def connect(self) -> list:
        """Open the configured ports; returns a list of problems ('' = all fine)."""
        problems = []
        need_rig = self.ptt_method in ("CAT", "RTS", "DTR") or (self.is_codan and self.ptt_method != "TNC")
        need_ptc = self.ptt_method == "TNC"
        rig_port = str(self.cfg.get("RIG_SERIAL_PORT", "") or "")
        ptc_port = str(self.cfg.get("PTC_SERIAL_PORT", "") or "")

        if rig_port and need_rig:
            try:
                self.rig.open(rig_port, int(self.cfg.get("RIG_BAUD", 9600)))
                self.log(f"RIG {rig_port} @ {self.rig.baud} geöffnet ({self.cat_protocol}, PTT {self.ptt_method})")
            except Exception as exc:
                problems.append(f"RIG {rig_port}: {exc}")
        elif need_rig:
            problems.append("Kein RIG COM Port eingestellt (PTT Methode CAT/RTS/DTR braucht ihn)")

        if ptc_port and need_ptc:
            try:
                self.ptc.open(ptc_port, int(self.cfg.get("PTC_BAUD", 57600)))
                self.log(f"PTC {ptc_port} @ {self.ptc.baud} geöffnet")
                self._ensure_ptc_terminal_mode()
            except Exception as exc:
                problems.append(f"PTC {ptc_port}: {exc}")
        elif need_ptc:
            problems.append("Kein PTC COM Port eingestellt (PTT Methode TNC braucht das Modem)")
        return problems

    def disconnect(self):
        self.rig.close()
        self.ptc.close()
        self._modem_trx_setup_for = ""
        self.log("Verbindung getrennt")

    @property
    def connected(self) -> bool:
        if self.ptt_method == "TNC":
            return self.ptc.is_open
        if self.ptt_method == "VOX" and not self.is_codan:
            return True
        return self.rig.is_open

    def status_text(self) -> str:
        parts = []
        parts.append(f"RIG {self.rig.port} ✓" if self.rig.is_open else "RIG –")
        parts.append(f"PTC {self.ptc.port} ✓" if self.ptc.is_open else "PTC –")
        return " | ".join(parts) + f" | PTT {self.ptt_method}"

    # ------------------------------------------------------------- PTC modem
    def _ensure_ptc_terminal_mode(self) -> bool:
        """Leave a hostmode another program (HFChat) left on, then wait for cmd:."""
        self.ptc.clear_recent()
        self.ptc.write(hostmode_exit_bytes())
        time.sleep(0.3)
        self.ptc.write(b"\r")
        if self.ptc.wait_for(lambda t: "CMD:" in t.upper(), 2.0) is None:
            self.ptc.write(b"\x1b\r")   # ESC: back to the cmd: prompt
            if self.ptc.wait_for(lambda t: "CMD:" in t.upper(), 2.0) is None:
                self.log("PTC: kein 'cmd:' Prompt – läuft HFChat noch oder stimmt die Baudrate?")
                return False
        if not self.detected_modem:
            self.ptc.write(b"VER\r")
            self.ptc.wait_for(lambda t: "CMD:" in t.upper(), 1.5)
        return True

    def modem_type(self) -> str:
        chosen = str(self.cfg.get("PTC_MODEM_TYPE", "AUTO") or "AUTO").upper()
        return self.detected_modem if chosen == "AUTO" else chosen

    def _ptc_command(self, command: str, wait: float = 1.5) -> Optional[str]:
        self.ptc.clear_recent()
        self.ptc.write((command + "\r").encode("latin-1", errors="ignore"))
        self.log(f"PTC ← {command}")
        return self.ptc.wait_for(lambda t: "CMD:" in t.upper() or "ERROR" in t.upper()
                                 or "NO SUCH" in t.upper(), wait)

    def _ensure_modem_trx_setup(self):
        profile = self.profile
        if profile is None or self._modem_trx_setup_for == profile.name:
            return
        for command in profile.modem_trx_commands(self.modem_type()):
            self._ptc_command(command)
        self._modem_trx_setup_for = profile.name

    # ---------------------------------------------------------------- Codan
    def codan_command_text(self, kind: str, to_id: str, self_id: str, message: str = "") -> str:
        key, default, _name = CODAN_CALLS.get(kind, CODAN_CALLS["selcall"])
        template = str(self.cfg.get(key, default) or default)
        msg = str(message or "").replace('"', "'").replace("\r", " ").replace("\n", " ").strip()
        text = template.replace("{to}", to_id).replace("{self}", self_id).replace("{msg}", msg)
        if (self.cfg.get("CODAN_SEND_SELF_ID", False) and "{self}" not in template and self_id
                and "{to}" in template):
            text += f" from {self_id}"
        return text.strip()

    def send_codan_cics(self, command: str) -> str:
        """Hand a CICS command to the Codan; '' = sent without error, else the problem."""
        if self.ptt_method == "TNC":
            if not self.ptc.is_open:
                return "PTC (Modem) ist nicht verbunden"
            if not self._ensure_ptc_terminal_mode():
                return "PTC ist nicht im Terminalmodus (cmd:)"
            self._ensure_modem_trx_setup()
            self.remember_sent(command)
            reply = self._ptc_command(f"TRX T {command}", wait=3.0)
            if reply and ("ERROR" in reply.upper() or "NO SUCH" in reply.upper()):
                return f"Modem/Funkgerät meldet: {reply}"
            return ""
        if not self.rig.is_open:
            return "RIG COM Port (Codan CICS) ist nicht verbunden"
        self.rig.clear_recent()
        self.remember_sent(command)
        self.rig.write((command + "\r").encode("ascii", errors="ignore"))
        self.log(f"RIG ← {command}")
        reply = self.rig.wait_for(lambda t: "ERROR" in t.upper() or "OK" in t.upper(), 2.0)
        if reply and "ERROR" in reply.upper():
            return f"Codan meldet: {reply}"
        return ""

    # ------------------------------------------------------------------ PTT
    def _civ_address(self) -> int:
        profile = self.profile
        raw = str(self.cfg.get("CAT_ADDRESS", "") or "").strip().lstrip("$")
        if raw:
            try:
                return int(raw, 16) & 0xFF
            except ValueError:
                pass
        if profile is not None and getattr(profile, "address", None):
            return int(profile.address) & 0xFF
        return 0x94

    def _cat_ptt_bytes(self, active: bool) -> bytes:
        proto = self.cat_protocol.upper()
        if proto == "ICOM":
            return b"\xFE\xFE" + bytes([self._civ_address(), 0xE0, 0x1C, 0x00, 0x01 if active else 0x00]) + b"\xFD"
        if proto == "YAESU":
            return b"TX1;" if active else b"TX0;"
        if proto == "KENWOOD":
            return b"TX;" if active else b"RX;"
        return b""

    def can_key_audio(self) -> str:
        """'' when the PC can key the radio for audio it plays, else why not."""
        method = self.ptt_method
        if method == "VOX":
            return ""
        if method == "TNC":
            return ("PTT Methode TNC: das Modem schaltet das Funkgerät, die PC-Soundkarte ist "
                    "nicht mit dem Funkgerät verbunden. Mit TNC geht SelCall nur mit einem Codan "
                    "(CICS-Befehl). Für IC-7300 & Co. PTT Methode CAT/RTS/DTR wählen.")
        if not self.rig.is_open:
            return "RIG COM Port ist nicht verbunden"
        if method == "CAT" and not self._cat_ptt_bytes(True):
            return f"CAT-Protokoll {self.cat_protocol} hat keinen PTT-Befehl – RTS oder DTR wählen"
        return ""

    def _icom_ptt(self, active: bool, frame: bytes) -> bool:
        """CI-V PTT with the radio's answer: FB = done, FA = refused, nothing = no link."""
        addr = f"{self._civ_address():02X}"
        ok_hex, ng_hex = f"E0 {addr} FB FD", f"E0 {addr} FA FD"
        self.rig.clear_recent()
        if not self.rig.write(frame):
            self.log("PTT: RIG COM Port nicht offen")
            return False
        reply = self.rig.wait_for(lambda t: ok_hex in t or ng_hex in t, 0.6)
        state = "EIN" if active else "AUS"
        if reply and ng_hex in reply:
            self.log(f"PTT {state}: Funkgerät lehnt ab (FA). Häufig: Frequenz außerhalb der Amateurbänder "
                     f"(IC-7300 sendet z.B. nicht auf Codan-Kanälen wie 4947 kHz), TX gesperrt, oder "
                     f"Betriebsart ohne Senden.")
            return False
        if reply is None:
            # some set-ups do not answer: ask the TX state (1C 00) instead
            self.rig.clear_recent()
            self.rig.write(b"\xFE\xFE" + bytes([self._civ_address(), 0xE0, 0x1C, 0x00]) + b"\xFD")
            want = f"E0 {addr} 1C 00 0{1 if active else 0} FD"
            if self.rig.wait_for(lambda t: want in t, 0.6) is None:
                self.log(f"PTT {state}: KEINE Antwort vom Funkgerät auf CI-V {addr}h – RIG COM Port, "
                         f"RIG Baudrate (IC-7300: MENU > SET > Connectors > CI-V > CI-V USB Baud Rate) "
                         f"und CI-V Adresse prüfen, oder '🔍 Automatisch erkennen'.")
                return not active   # releasing PTT never counts as failed
        self.log(f"PTT {state} (CAT, Funkgerät bestätigt)")
        return True

    def set_ptt(self, active: bool) -> bool:
        method = self.ptt_method
        try:
            if method == "VOX":
                return True
            if method == "CAT":
                data = self._cat_ptt_bytes(active)
                if not data:
                    self.log(f"PTT: Protokoll {self.cat_protocol} hat keinen PTT-Befehl – RTS/DTR wählen")
                    return False
                if self.cat_protocol.upper() == "ICOM":
                    return self._icom_ptt(active, data)
                if not self.rig.write(data):
                    self.log("PTT: RIG COM Port nicht offen")
                    return False
            elif method == "RTS":
                self.rig.set_lines(rts=active)
            elif method == "DTR":
                self.rig.set_lines(dtr=active)
            else:
                return False
            self.log(f"PTT {'EIN' if active else 'AUS'} ({method})")
            return True
        except Exception as exc:
            self.log(f"PTT Fehler: {exc}")
            return False
