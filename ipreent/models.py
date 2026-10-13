"""Printer model parameters, extracted from the vendor app (models.json)."""
import json
from dataclasses import dataclass
from pathlib import Path

_TABLE = None


@dataclass
class Model:
    name: str = "generic"
    width: int = 384          # printable dots per line
    dpi: int = 200
    img_speed: int = 30
    text_speed: int = 25
    energy: int = 0           # 0 = don't send an energy command (printer default)
    rle: bool = False         # supports BF compressed lines
    new_format: bool = False  # frames prefixed with 0x12
    mtu: int = 123
    interval_ms: int = 6
    use_spp: bool = False


def _table():
    global _TABLE
    if _TABLE is None:
        _TABLE = json.loads((Path(__file__).with_name("models.json")).read_text())
    return _TABLE


def lookup(ble_name):
    """Longest modelNo that prefixes the advertised name, like the vendor app."""
    best = None
    for m in _table():
        if ble_name and ble_name.startswith(m["modelNo"]) and m["modelNo"]:
            if best is None or len(m["modelNo"]) > len(best["modelNo"]):
                best = m
    if best is None:
        return Model()
    return Model(
        name=best["modelNo"],
        width=best["printSize"] if best["size"] == 2 else best["paperSize"],
        dpi=best["dpi"],
        img_speed=best["imgSpeed"],
        text_speed=best["textSpeed"],
        energy=best["midEnergy"] if isinstance(best["midEnergy"], int) else 0,
        rle=bool(best["newCompress"]),
        new_format=bool(best["newFormat"]),
        mtu=best["mtu"] or 123,
        interval_ms=best["interval"] or 6,
        use_spp=bool(best["useSPP"]),
    )


def is_known(ble_name):
    return lookup(ble_name).name != "generic"
