"""Automatic set-up: find the radio's COM port, the modem's COM port and the
sound card that belongs to the radio.

COM ports are found by asking each port a harmless question (read the
frequency, or a CR to the modem); nothing is transmitted on air.

The sound card: an IC-7300, IC-7610, IC-705, FT-991A ... has one USB cable
with a USB hub inside: the COM port (CP210x) and the "USB Audio CODEC" hang
on the same hub.  On Windows the device tree tells which sound card sits on
the same hub as the radio's COM port.  If that is not possible, the device
names are used ("USB Audio CODEC", "USB PnP Sound Device", ...).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from typing import Callable, Dict, List, Optional, Tuple

try:
    import serial
    import serial.tools.list_ports
except ImportError:  # pragma: no cover
    serial = None

from radio_link import hostmode_exit_bytes

RIG_PROBE_BAUDS = {
    "ICOM": (115200, 19200, 9600, 38400, 57600, 4800),
    "YAESU": (38400, 4800, 9600, 19200, 57600, 115200),
    "KENWOOD": (115200, 57600, 38400, 9600, 19200, 4800),
    "CODAN": (9600, 19200, 4800, 38400, 57600, 115200),
}
PTC_PROBE_BAUDS = (57600, 115200, 38400, 19200, 9600)

# Sound cards of radios and interfaces, best match first.
RADIO_AUDIO_NAMES = ("USB AUDIO CODEC", "USB PNP SOUND", "C-MEDIA", "SIGNALINK", "DIGIRIG",
                     "USB SOUND", "USB AUDIO DEVICE", "USB-AUDIO")
PC_AUDIO_NAMES = ("REALTEK", "INTEL", "HDMI", "NVIDIA", "AMD HIGH", "DISPLAY", "BLUETOOTH",
                  "HEADSET", "WEBCAM", "STEREO MIX", "STEREOMIX", "PRIMARY", "PRIMÄR", "MICROSOFT SOUND MAPPER",
                  "SOUND MAPPER", "VIRTUAL", "VB-AUDIO", "CABLE")


# ----------------------------------------------------------------- COM ports
def _open(port: str, baud: int):
    ser = serial.Serial()
    ser.port, ser.baudrate, ser.timeout, ser.write_timeout = port, baud, 0.05, 1
    ser.dtr = False      # never key a radio that uses DTR/RTS as PTT
    ser.rts = False
    ser.open()
    return ser


def _ask(ser, data: bytes, wait: float = 0.35) -> bytes:
    ser.reset_input_buffer()
    ser.write(data)
    ser.flush()
    end, got = time.time() + wait, b""
    while time.time() < end:
        chunk = ser.read(256)
        if chunk:
            got += chunk
    return got


def icom_reply_address(reply: bytes) -> Optional[int]:
    """Radio address from a CI-V frequency answer FE FE E0 <radio> 03 ... FD."""
    match = re.search(rb"\xFE\xFE\xE0(.)\x03.{5}\xFD", reply, re.DOTALL)
    return match.group(1)[0] if match else None


def probe_rig(port: str, protocol: str, civ_address: int = 0x94, bauds=None) -> Optional[dict]:
    """{'port', 'baud', 'protocol', 'address'?} when the radio answers on this port."""
    protocol = protocol.upper()
    for baud in bauds or RIG_PROBE_BAUDS.get(protocol, (9600,)):
        try:
            ser = _open(port, baud)
        except Exception:
            return None          # port busy / missing: no need to try other speeds
        try:
            if protocol == "ICOM":
                for addr in dict.fromkeys((civ_address, 0x00)):
                    found = icom_reply_address(_ask(ser, bytes([0xFE, 0xFE, addr, 0xE0, 0x03, 0xFD])))
                    if found is not None:
                        return {"port": port, "baud": baud, "protocol": "ICOM", "address": found}
            elif protocol in ("YAESU", "KENWOOD"):
                reply = _ask(ser, b"FA;")
                if re.search(rb"FA\d{8,11};", reply):
                    return {"port": port, "baud": baud, "protocol": protocol}
            elif protocol == "CODAN":
                reply = _ask(ser, b"\rFREQ\r", wait=0.8).upper()
                if b"FREQ" in reply and (b"=" in reply or b":" in reply) or b"ERROR" in reply:
                    return {"port": port, "baud": baud, "protocol": "CODAN"}
        except Exception:
            pass
        finally:
            ser.close()
    return None


def probe_ptc(port: str, bauds=PTC_PROBE_BAUDS) -> Optional[dict]:
    """{'port', 'baud', 'modem'} when a SCS PACTOR modem answers with 'cmd:'."""
    for baud in bauds:
        try:
            ser = _open(port, baud)
        except Exception:
            return None
        try:
            ser.write(hostmode_exit_bytes())
            time.sleep(0.2)
            reply = _ask(ser, b"\r", wait=0.6)
            if b"cmd:" not in reply.lower():
                reply = _ask(ser, b"\x1b\r", wait=0.6)
            if b"cmd:" in reply.lower():
                ver = _ask(ser, b"VER\r", wait=0.8).upper()
                modem = ""
                for name in (b"DR-9400", b"DR-7800", b"DR-7400", b"PTC-III", b"PTC-II"):
                    if name in ver:
                        modem = "PTC-II" if name.startswith(b"PTC") else name.decode()
                        break
                return {"port": port, "baud": baud, "modem": modem}
        except Exception:
            pass
        finally:
            ser.close()
    return None


def port_list() -> List[dict]:
    if serial is None:
        return []
    result = []
    for p in serial.tools.list_ports.comports():
        result.append({"device": p.device, "description": p.description or "", "hwid": p.hwid or "",
                       "vid": p.vid, "serial": p.serial_number or ""})
    return result


def _rig_first(ports: List[dict]) -> List[dict]:
    """Radios with a CP210x / FTDI USB bridge first, Bluetooth ports last."""
    def rank(p):
        text = (p["description"] + " " + p["hwid"] + " " + p["serial"]).upper()
        if re.search(r"IC-|FT-|TS-", text):
            return 0
        if "CP210" in text or "10C4:EA60" in text or "SILICON LABS" in text:
            return 1
        if "BLUETOOTH" in text or "BTHENUM" in text:
            return 9
        return 5
    return sorted(ports, key=rank)


# --------------------------------------------------------------- sound cards
def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", str(name or "")).strip().upper()


def _inner(name: str) -> str:
    """'Lautsprecher (2- USB Audio CODEC)' -> '2- USB AUDIO CODEC'."""
    match = re.search(r"\(([^()]*)\)\s*$", str(name or ""))
    return _norm(match.group(1) if match else name)


def guess_by_name(names: List[str]) -> Optional[str]:
    """Best radio-looking sound card by name, None if nothing fits."""
    best, best_rank = None, 99
    usb_only = []
    for name in names:
        up = _norm(name)
        if any(bad in up for bad in PC_AUDIO_NAMES):
            continue
        for rank, word in enumerate(RADIO_AUDIO_NAMES):
            if word in up and rank < best_rank:
                best, best_rank = name, rank
        if "USB" in up or "CODEC" in up or re.search(r"\bIC-|\bFT-|\bTS-", up):
            usb_only.append(name)
    if best is None and len(usb_only) == 1:
        best = usb_only[0]       # the only USB sound card on the PC
    return best


def pick_partner(inputs: List[str], output_name: str) -> Optional[str]:
    """Input device of the same sound card as the output device."""
    inner = _inner(output_name)
    for name in inputs:
        if _inner(name) == inner:
            return name
    return None


_WINDOWS_TREE_PS = r"""
$ErrorActionPreference = 'SilentlyContinue'
$out = @()
Get-PnpDevice -PresentOnly | Where-Object { $_.Class -eq 'Ports' -or $_.Class -eq 'AudioEndpoint' } | ForEach-Object {
  $chain = @(); $p = $_.InstanceId
  for ($i = 0; $i -lt 8; $i++) {
    $p = (Get-PnpDeviceProperty -InstanceId $p -KeyName DEVPKEY_Device_Parent).Data
    if (-not $p) { break }
    $chain += $p
  }
  $out += [pscustomobject]@{ Class = $_.Class; Name = $_.FriendlyName; Id = $_.InstanceId; Parents = $chain }
}
$out | ConvertTo-Json -Depth 4 -Compress
"""


def windows_device_tree() -> List[dict]:
    if not sys.platform.startswith("win"):
        return []
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _WINDOWS_TREE_PS],
                              capture_output=True, text=True, timeout=40, creationflags=flags)
        data = json.loads(proc.stdout or "[]")
    except Exception:
        return []
    if isinstance(data, dict):
        data = [data]
    for item in data:
        parents = item.get("Parents") or []
        item["Parents"] = [parents] if isinstance(parents, str) else list(parents)
    return data


def _shared_hub(port_parents: List[str], audio_parents: List[str]) -> Optional[int]:
    """How many steps above the COM port the first common USB hub is (None = none).

    Root hubs and host controllers do not count: everything on the PC
    shares those.
    """
    audio_set = {p.upper() for p in audio_parents}
    for depth, parent in enumerate(port_parents):
        up = parent.upper()
        if "ROOT_HUB" in up or not up.startswith("USB\\"):
            return None
        if up in audio_set:
            return depth
    return None


def audio_for_com_port(com_port: str, tree: List[dict]) -> Tuple[Optional[str], Optional[str]]:
    """(output name, input name) of the sound card on the same USB device as com_port."""
    port_dev = None
    for item in tree:
        if item.get("Class") == "Ports" and re.search(rf"\({re.escape(com_port)}\)\s*$", str(item.get("Name", ""))):
            port_dev = item
            break
    if port_dev is None:
        return None, None
    best = {}
    for item in tree:
        if item.get("Class") != "AudioEndpoint":
            continue
        depth = _shared_hub(port_dev["Parents"], item["Parents"])
        if depth is None:
            continue
        # render endpoints: {0.0.0.*}, capture endpoints: {0.0.1.*}
        kind = "in" if "{0.0.1." in str(item.get("Id", "")) else "out"
        if kind not in best or depth < best[kind][0]:
            best[kind] = (depth, str(item.get("Name", "")))
    return (best.get("out", (0, None))[1], best.get("in", (0, None))[1])


def match_name(wanted: Optional[str], names: List[str]) -> Optional[str]:
    """Windows' full endpoint name vs. the (MME, max 31 chars) name sounddevice shows."""
    if not wanted:
        return None
    w = _norm(wanted)
    for name in names:
        n = _norm(name)
        if n == w or (len(n) >= 20 and w.startswith(n)):
            return name
    inner = _inner(wanted)
    hits = [name for name in names if _inner(name) == inner]
    return hits[0] if len(hits) == 1 else None


# ------------------------------------------------------------------ all
def detect(cfg: dict, outputs: List[str], inputs: List[str], log: Callable[[str], None],
           want_rig: bool = True, want_ptc: bool = True) -> Dict[str, object]:
    """Find RIG port, PTC port and the radio's sound card.  Returns cfg keys to set."""
    found: Dict[str, object] = {}
    ports = port_list()
    log(f"COM Ports: {', '.join(p['device'] for p in ports) or 'keine'}")
    protocol = str(cfg.get("CAT_PROTOCOL", "ICOM") or "ICOM").upper()
    try:
        civ = int(str(cfg.get("CAT_ADDRESS", "94") or "94").lstrip("$"), 16)
    except ValueError:
        civ = 0x94
    used = set()

    if want_ptc:
        for p in ports:
            log(f"Suche Modem an {p['device']} …")
            hit = probe_ptc(p["device"])
            if hit:
                log(f"Modem gefunden: {hit['port']} @ {hit['baud']} Bd {hit['modem']}".strip())
                found.update({"PTC_SERIAL_PORT": hit["port"], "PTC_BAUD": hit["baud"]})
                if hit["modem"]:
                    found["PTC_MODEM_TYPE"] = hit["modem"]
                used.add(hit["port"])
                break

    if want_rig:
        for p in _rig_first([p for p in ports if p["device"] not in used]):
            log(f"Suche Funkgerät ({protocol}) an {p['device']} …")
            hit = probe_rig(p["device"], protocol, civ)
            if hit:
                text = f"Funkgerät gefunden: {hit['port']} @ {hit['baud']} Bd"
                if hit.get("address") is not None:
                    text += f", CI-V {hit['address']:02X}h"
                    found["CAT_ADDRESS"] = f"{hit['address']:02X}"
                log(text)
                found.update({"RIG_SERIAL_PORT": hit["port"], "RIG_BAUD": hit["baud"]})
                break
        else:
            log("Kein Funkgerät hat geantwortet (CAT/CI-V am Gerät eingeschaltet? Protokoll richtig?)")

    rig_port = str(found.get("RIG_SERIAL_PORT") or cfg.get("RIG_SERIAL_PORT") or "")
    out_name = in_name = None
    if rig_port:
        tree = windows_device_tree()
        if tree:
            win_out, win_in = audio_for_com_port(rig_port, tree)
            out_name, in_name = match_name(win_out, outputs), match_name(win_in, inputs)
            if out_name:
                log(f"Soundkarte am selben USB-Gerät wie {rig_port}: {out_name}")
    if not out_name:
        out_name = guess_by_name(outputs)
        if out_name:
            log(f"Soundkarte nach Name gewählt: {out_name}")
    if out_name and not in_name:
        in_name = pick_partner(inputs, out_name) or guess_by_name(inputs)
    if out_name:
        found["AUDIO_OUT"] = out_name
    else:
        log("Keine Funkgeräte-Soundkarte gefunden – bitte von Hand wählen")
    if in_name:
        found["AUDIO_IN"] = in_name
    return found
