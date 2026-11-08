"""Radio models for the settings dialog.

Choosing a model fills in protocol, CI-V address and baud rate.  A file
``radios.txt`` next to the program can add models or change values::

    [CODAN NGT]
    protocol = CODAN
    baudrate = 9600
    ctype = 1          ; Codan command style: 0 Envoy, 1 NGT/2110, 2 CICS V2

    [IC-7300]
    protocol = ICOM
    baudrate = 115200
    address = 94       ; CI-V address, hex
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

RADIO_FILE_NAME = "radios.txt"

# The DR-9400 has no Codan TRX type: it gets the Kenwood type for speed and
# interface only, the Codan text commands pass through "TRX T".
KENWOOD_FOR_CODAN_MODEM = "DR-9400"


@dataclass(frozen=True)
class RadioModel:
    name: str
    protocol: str                 # CODAN, ICOM, YAESU, KENWOOD
    baudrate: int = 9600
    address: Optional[int] = None  # Icom CI-V
    ctype: int = 1                 # Codan command style

    @property
    def is_codan(self) -> bool:
        return self.protocol == "CODAN"

    def cat_protocol(self) -> str:
        return {"CODAN": "CODAN", "ICOM": "ICOM", "YAESU": "Yaesu", "KENWOOD": "Kenwood"}.get(self.protocol, "ICOM")

    @property
    def group(self) -> str:
        return {"CODAN": "Codan", "ICOM": "Icom", "YAESU": "Yaesu", "KENWOOD": "Kenwood / Elecraft"}.get(
            self.protocol, "Andere")

    def modem_trx_commands(self, modem_type: str = "") -> List[str]:
        """SCS modem commands that prepare its TRX port for a Codan."""
        if not self.is_codan:
            return []
        if str(modem_type or "").upper() == KENWOOD_FOR_CODAN_MODEM:
            return [f"TRX TY K {self.baudrate} A V24", "TRX PARITY 0", "TRX RTS 1"]
        return [f"TRX TY C {self.baudrate} A V24"]

    def summary(self) -> str:
        parts = [self.protocol, f"{self.baudrate} Bd"]
        if self.address is not None:
            parts.append(f"CI-V {self.address:02X}h")
        if self.is_codan:
            parts.append({0: "Envoy", 1: "NGT / 2110", 2: "CICS V2"}.get(self.ctype, ""))
        return " · ".join(p for p in parts if p)


_BUILTIN = [
    RadioModel("CODAN ENVOY", "CODAN", 9600, ctype=0),
    RadioModel("CODAN NGT", "CODAN", 9600, ctype=1),
    RadioModel("CODAN 2110", "CODAN", 9600, ctype=1),
    RadioModel("CODAN 9323", "CODAN", 9600, ctype=2),
    RadioModel("CODAN 9360", "CODAN", 9600, ctype=2),
    RadioModel("CODAN 9390", "CODAN", 9600, ctype=2),
    RadioModel("CODAN 9780", "CODAN", 9600, ctype=2),
    RadioModel("IC-7300", "ICOM", 115200, address=0x94),
    RadioModel("IC-7610", "ICOM", 115200, address=0x98),
    RadioModel("IC-705", "ICOM", 115200, address=0xA4),
    RadioModel("IC-7100", "ICOM", 19200, address=0x88),
    RadioModel("IC-7200", "ICOM", 19200, address=0x76),
    RadioModel("IC-718", "ICOM", 9600, address=0x5E),
    RadioModel("IC-M802", "ICOM", 9600, address=0x08),
    RadioModel("FT-991A", "YAESU", 38400),
    RadioModel("FT-891", "YAESU", 38400),
    RadioModel("FT-710", "YAESU", 38400),
    RadioModel("FT-450D", "YAESU", 4800),
    RadioModel("TS-590SG", "KENWOOD", 115200),
    RadioModel("TS-2000", "KENWOOD", 9600),
]


def _parse(text: str) -> Dict[str, RadioModel]:
    models: Dict[str, RadioModel] = {}
    name, values = None, {}

    def _flush():
        if not name or not values.get("protocol"):
            return
        proto = values["protocol"].strip().upper()
        proto = {"CODAN-CICS": "CODAN", "ICOM-CIV": "ICOM", "KENWOOD-11": "KENWOOD"}.get(proto, proto)
        if proto.startswith("YAESU"):
            proto = "YAESU"
        address = values.get("address", "").strip().lstrip("$")
        try:
            addr = int(address, 16) if address else None
        except ValueError:
            addr = None
        try:
            baud = int(values.get("baudrate", "9600"))
        except ValueError:
            baud = 9600
        try:
            ctype = int(values.get("ctype", "1"))
        except ValueError:
            ctype = 1
        models[name] = RadioModel(name, proto, baud, addr, ctype)

    for raw in str(text or "").splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        section = re.match(r"^\[(.+)\]$", line)
        if section:
            _flush()
            name, values = section.group(1).strip().upper(), {}
        elif "=" in line and name:
            key, value = line.split("=", 1)
            values[key.strip().lower()] = value.strip()
    _flush()
    return models


def load_models(directory: str) -> Dict[str, RadioModel]:
    models = {m.name: m for m in _BUILTIN}
    try:
        with open(os.path.join(directory, RADIO_FILE_NAME), "r", encoding="utf-8", errors="replace") as handle:
            models.update(_parse(handle.read()))
    except OSError:
        pass
    return models


def grouped_names(models: Dict[str, RadioModel]) -> List[tuple]:
    order = ["Codan", "Icom", "Yaesu", "Kenwood / Elecraft", "Andere"]
    groups: Dict[str, List[str]] = {}
    for model in models.values():
        groups.setdefault(model.group, []).append(model.name)
    return [(label, groups[label]) for label in order if label in groups]
