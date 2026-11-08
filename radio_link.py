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
        ser.timeout = 0.03        # short: CI-V answers (no line end) are passed on quickly
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
        """True only when the radio this program talks to speaks Codan CICS.

        Direct on the PC (CAT/RTS/DTR) that is decided by the CAT protocol: an
        Icom on the RIG port never gets CICS text, whatever radio model is
        chosen.  Through the modem (TNC) the radio model decides.
        """
        if self.ptt_method == "TNC":
            profile = self.profile
            return bool(profile.is_codan) if profile is not None else self.cat_protocol == "CODAN"
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
                if self.cat_protocol.upper() == "ICOM" and self.ptt_method == "CAT":
                    problem = self._icom_find_baud(rig_port)
                    if problem:
                        problems.append(problem)
            except Exception as exc:
                problems.append(f"RIG {rig_port}: {exc}")
        elif need_rig:
            problems.append("Kein RIG COM Port eingestellt (PTT Methode CAT/RTS/DTR braucht ihn)")

        if ptc_port and need_ptc:
            try:
                self.ptc.open(ptc_port, int(self.cfg.get("PTC_BAUD", 57600)))
                self.log(f"PTC {ptc_port} @ {self.ptc.baud} geöffnet")
                if not self._ensure_ptc_terminal_mode():
                    self._ptc_find_baud(ptc_port)
            except Exception as exc:
                problems.append(f"PTC {ptc_port}: {exc}")
        elif need_ptc:
            problems.append("Kein PTC COM Port eingestellt (PTT Methode TNC braucht das Modem)")
        return problems

    # ------------------------------------------------- find the baud rate
    ICOM_BAUDS = (115200, 19200, 9600, 38400, 57600, 4800)
    cfg_changed = False

    def icom_alive(self) -> bool:
        """The Icom answers a 'read frequency' (03) on CI-V."""
        return self.icom_query(b"\x03", 5, timeout=0.5) is not None

    def _port_is_modem(self) -> bool:
        """A SCS PACTOR modem answers a CR with 'cmd:' - then this is not the radio."""
        self.rig.clear_recent()
        self.rig.write(b"\r")
        return self.rig.wait_for(lambda t: "CMD:" in t.upper() or "PTC" in t.upper(), 0.6) is not None

    def _icom_try_bauds(self, port: str) -> bool:
        for baud in self.ICOM_BAUDS:
            try:
                self.rig.open(port, baud)
            except Exception:
                return False                     # port busy / gone
            if self.icom_alive():
                return True
        return False

    def _icom_find_baud(self, port: str) -> str:
        """The Icom does not answer: wrong port (e.g. the modem's) or wrong baud rate.
        Try the other baud rates, then the other COM ports, and keep what works."""
        if self.icom_alive():
            return ""
        first = self.rig.baud
        if self._port_is_modem():
            self.log(f"Auf {port} antwortet das PACTOR-Modem, nicht das Funkgerät – suche das IC-7300 "
                     f"an den anderen COM Ports …")
        else:
            self.log(f"IC-7300 antwortet nicht auf {port} mit {first} Bd – probiere andere Baudraten …")
            if self._icom_try_bauds(port):
                self.cfg["RIG_BAUD"] = self.rig.baud
                self.cfg_changed = True
                self.log(f"IC-7300 antwortet mit {self.rig.baud} Bd – übernommen. (Steht am Funkgerät "
                         f"'CI-V USB Port' auf 'Link to [REMOTE]', gilt die REMOTE-Baudrate. Besser: MENU > SET > "
                         f"Connectors > CI-V > CI-V USB Port = Unlink from [REMOTE].)")
                return ""
        modem_port = str(self.cfg.get("PTC_SERIAL_PORT", "") or "")
        for other in list_serial_ports():
            if other in (port, modem_port):
                continue
            self.log(f"Suche IC-7300 an {other} …")
            if self._icom_try_bauds(other):
                self.cfg["RIG_SERIAL_PORT"] = other
                self.cfg["RIG_BAUD"] = self.rig.baud
                self.cfg_changed = True
                self.log(f"IC-7300 gefunden: {other} @ {self.rig.baud} Bd – als RIG COM Port übernommen")
                return ""
        try:
            self.rig.open(port, first)
        except Exception:
            pass
        return (f"Das IC-7300 antwortet an keinem COM Port (CI-V {self._civ_address():02X}h). "
                f"Eingeschaltet und per USB verbunden? Am IC-7300: MENU > SET > Connectors > CI-V: "
                f"CI-V Address 94h, CI-V USB Port = Unlink from [REMOTE]. Läuft HFChat/ein anderes "
                f"CAT-Programm auf dem COM Port des Funkgeräts?")

    def _ptc_find_baud(self, port: str):
        first = self.ptc.baud
        for baud in (57600, 115200, 38400, 19200, 9600):
            if baud == first:
                continue
            self.ptc.open(port, baud)
            if self._ensure_ptc_terminal_mode():
                self.cfg["PTC_BAUD"] = baud
                self.cfg_changed = True
                self.log(f"Modem antwortet mit {baud} Bd – übernommen")
                return
        self.ptc.open(port, first)
        self.log("Modem antwortet mit keiner Baudrate – eingeschaltet? HFChat beendet?")

    def disconnect(self):
        self.usb_data_set = False
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
        if self.cat_protocol != "CODAN":
            return (f"Am RIG Port ist ein {self.cat_protocol}-Funkgerät eingestellt, kein Codan – "
                    f"CICS-Befehle gehen nur an einen Codan")
        self.rig.clear_recent()
        self.remember_sent(command)
        self.rig.write((command + "\r").encode("ascii", errors="ignore"))
        self.log(f"RIG ← {command}")
        reply = self.rig.wait_for(lambda t: "ERROR" in t.upper() or "OK" in t.upper(), 2.0)
        if reply and "ERROR" in reply.upper():
            return f"Codan meldet: {reply}"
        if reply is None and not self.rig.wait_for(lambda t: True, 0.1):
            self.log("WARNUNG: keine Antwort vom Codan – CICS eingeschaltet? Baudrate richtig?")
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

    # ------------------------------------------------------- Icom extras
    def icom_query(self, payload: bytes, reply_len: int, timeout: float = 0.6) -> Optional[bytes]:
        """Send FE FE <radio> E0 <payload> FD, return the data bytes of the answer."""
        if not self.rig.is_open:
            return None
        addr = self._civ_address()
        head = f"E0 {addr:02X} " + " ".join(f"{b:02X}" for b in payload)
        self.rig.clear_recent()
        self.rig.write(b"\xFE\xFE" + bytes([addr, 0xE0]) + payload + b"\xFD")
        line = self.rig.wait_for(lambda t: head in t and "FD" in t[t.find(head):], timeout)
        if line is None:
            return None
        rest = line[line.find(head) + len(head):].split()
        data = []
        for item in rest:
            if item == "FD":
                break
            data.append(int(item, 16))
        return bytes(data[:reply_len]) if len(data) >= reply_len else None

    def icom_meter(self, which: str) -> Optional[int]:
        """Po or ALC meter 0..255 (CI-V 15 11 / 15 13), None if not readable."""
        sub = {"PO": 0x11, "ALC": 0x13, "SWR": 0x12}[which.upper()]
        data = self.icom_query(bytes([0x15, sub]), 2, timeout=0.4)
        if data is None:
            return None
        try:
            return int(f"{data[0]:02X}{data[1]:02X}")      # BCD 0000..0255
        except ValueError:
            return None

    def icom_meters_max(self, seconds: float) -> tuple:
        """Highest Po and ALC (0..255) read again and again for `seconds`; (None, None) if unreadable."""
        end = time.time() + seconds
        po = alc = None
        while time.time() < end:
            value = self.icom_meter("PO")
            if value is not None:
                po = max(po or 0, value)
            value = self.icom_meter("ALC")
            if value is not None:
                alc = max(alc or 0, value)
        return po, alc

    def icom_set_usb_data(self) -> str:
        """Mode USB + DATA on (USB-D), as needed for audio from the USB sound card."""
        if not self.rig.is_open:
            return "RIG COM Port ist nicht verbunden"
        addr = self._civ_address()
        replies = []
        for payload in (b"\x06\x01\x01", b"\x1A\x06\x01\x01"):      # mode USB, data mode on (FIL1)
            self.rig.clear_recent()
            self.rig.write(b"\xFE\xFE" + bytes([addr, 0xE0]) + payload + b"\xFD")
            reply = self.rig.wait_for(lambda t: f"E0 {addr:02X} FB FD" in t or f"E0 {addr:02X} FA FD" in t, 1.5)
            replies.append("OK" if reply and "FB" in reply else ("abgelehnt" if reply else "keine Antwort"))
        self.log(f"Funkgerät auf USB-D: Mode USB {replies[0]}, DATA {replies[1]}")
        self.usb_data_set = replies[1] == "OK"
        return "" if replies == ["OK", "OK"] else f"Mode USB {replies[0]}, DATA {replies[1]}"

    # IC-7300 menu over CI-V (1A 05 00 nn): 0067 = DATA MOD, 0066 = DATA OFF MOD,
    # values 00 MIC, 01 ACC, 02 MIC,ACC, 03 USB, 04 MIC,USB.  The IC-7300MK2 uses 0085.
    MOD_NAMES = {0: "MIC", 1: "ACC", 2: "MIC,ACC", 3: "USB", 4: "MIC,USB", 5: "LAN"}

    def _icom_ack(self, payload: bytes, timeout: float = 1.0) -> Optional[bool]:
        """Write a CI-V command; True = FB, False = FA, None = no answer."""
        addr = self._civ_address()
        self.rig.clear_recent()
        self.rig.write(b"\xFE\xFE" + bytes([addr, 0xE0]) + payload + b"\xFD")
        reply = self.rig.wait_for(lambda t: f"E0 {addr:02X} FB FD" in t or f"E0 {addr:02X} FA FD" in t, timeout)
        if reply is None:
            return None
        return f"E0 {addr:02X} FB FD" in reply

    def _menu_item(self, key: str, default: str) -> bytes:
        raw = str(self.cfg.get(key, default) or default).strip()
        raw = raw if len(raw) == 4 and raw.isdigit() else default
        return bytes([int(raw[:2], 16), int(raw[2:], 16)])

    def _datamod_item(self) -> bytes:
        return self._menu_item("ICOM_DATAMOD_ITEM", "0067")

    def _dataoffmod_item(self) -> bytes:
        # DATA OFF MOD is the item before DATA MOD (IC-7300 0066, IC-7300MK2 0084)
        dm = self._datamod_item()
        n = int(f"{dm[0]:02X}{dm[1]:02X}") - 1
        return self._menu_item("ICOM_DATAOFFMOD_ITEM", f"{n:04d}")

    def icom_read_mod_sources(self) -> tuple:
        """(DATA OFF MOD, DATA MOD) as numbers, None where not readable.  Only reads."""
        def read(item):
            value = self.icom_query(b"\x1A\x05" + item, 1)
            return value[0] if value is not None and value[0] in self.MOD_NAMES else None
        return read(self._dataoffmod_item()), read(self._datamod_item())

    def icom_prepare_audio_tx(self) -> Optional[dict]:
        """Before audio TX: pick the mode whose audio source is USB, without
        touching the menu.

        The IC-7300 has two settings: DATA MOD (for USB-D, e.g. ACC for the
        PACTOR modem) and DATA OFF MOD (for plain USB).  With DATA OFF MOD =
        MIC,USB the selcall goes out in plain USB from the PC while PACTOR
        keeps ACC in USB-D.  Mode and DATA are put back afterwards.
        Returns None when nothing is to be done, {"blocked": text} when no mode
        takes audio from USB.
        """
        if not self.rig.is_open or self.ptt_method != "CAT" or self.cat_protocol.upper() != "ICOM":
            return None
        state = {}
        mode = self.icom_query(b"\x04", 2)                    # mode, filter
        data = self.icom_query(b"\x1A\x06", 2)                # data on/off, filter
        if mode is not None:
            state["mode"] = mode
        if data is not None:
            state["data"] = data
        if mode is None and data is None and not self.icom_alive():
            state["blocked"] = ("Das IC-7300 antwortet nicht über CI-V (COM Port / Baudrate / CI-V Adresse).\n"
                                "Verbindung trennen und neu verbinden – das Programm sucht dann die Baudrate.\n"
                                "Am IC-7300: MENU > SET > Connectors > CI-V > CI-V USB Port = Unlink from [REMOTE].")
            return state
        choice = str(self.cfg.get("ICOM_TX_SOURCE", "AUTO") or "AUTO").upper()
        off_mod, data_mod = self.icom_read_mod_sources()
        names = self.MOD_NAMES
        self.log(f"IC-7300 Tonquelle: USB → {names.get(off_mod, '?')} · USB-D → {names.get(data_mod, '?')}")
        usb = (3, 4)
        if choice == "USB":
            use_data = False
        elif choice == "USB-D":
            use_data = True
        elif off_mod in usb:
            use_data = False          # plain USB takes the PC sound: PACTOR (USB-D/ACC) untouched
        elif data_mod in usb:
            use_data = True
        elif off_mod is None and data_mod is None:
            use_data = True           # menu not readable: old behaviour
            self.log("Tonquelle nicht lesbar – sende in USB-D")
        else:
            state["blocked"] = (
                f"Am IC-7300 nimmt weder USB ({names.get(off_mod, '?')}) noch USB-D "
                f"({names.get(data_mod, '?')}) den Ton vom PC.\n\nEinmalig einstellen:\n"
                "MENU > SET > Connectors > MOD Input > DATA OFF MOD = MIC,USB\n\n"
                "DATA MOD bleibt auf ACC – PACTOR läuft weiter in USB-D, das Mikrofon geht weiter.")
            return state
        if mode is None or mode[0] != 0x01:
            self._icom_ack(b"\x06\x01\x01")                  # USB
        want = b"\x01\x01" if use_data else b"\x00\x00"
        if data is None or (data[0] != 0) != use_data:
            ok = self._icom_ack(b"\x1A\x06" + want)
            if ok is False and not use_data:
                self._icom_ack(b"\x1A\x06\x00")
        self.log(f"Selcall sendet in {'USB-D' if use_data else 'USB (DATA aus)'} – Menü unverändert")
        return state

    def icom_restore_audio_tx(self, state: Optional[dict]):
        """Put mode and DATA back as they were (PACTOR set-up)."""
        if not state or not self.rig.is_open:
            return
        if "mode" in state:
            self._icom_ack(b"\x06" + state["mode"])
        if "data" in state:
            self._icom_ack(b"\x1A\x06" + state["data"])

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
