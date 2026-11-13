"""Printer model parameters, extracted from the vendor app (models.json)."""
import json
from dataclasses import dataclass
from pathlib import Path

from .i18n import tr

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
    paper: int = 2            # vendor "size": paper class (see PAPER)
    labels: bool = False      # vendor "canPrintLabel": has a mode for die-cut labels


# The vendor's "size" codes, named from the print widths each one has in models.json:
# 1 = 96 dots (12 mm), 2 = 384/576 dots (48 mm), 3 = 576 dots at 200 dpi (72 mm),
# 4 = 800-1280 dots (100-110 mm), 8 = 1664-2592 dots (A4 width).
PAPER = {1: tr("narrow label tape (about 15 mm)"), 2: tr("57 mm thermal roll (sold as 57 or 58 mm)"),
         3: tr("80 mm thermal roll"), 4: tr("4-inch thermal labels or roll (about 110 mm)"), 8: tr("A4 thermal paper")}


def details(model):
    """What a person needs to know about the printer, as (label, value) pairs.

    Kept: what decides which paper to buy and how prints come out (labels only when supported).
    Left out on purpose: ink (there is none), paper speed, the
    transport tuning (MTU, chunk interval, compressed lines, frame format), the raw speed byte and
    energy numbers, and the vendor's internal flags (device id, retract length, sensor values).
    """
    mm = model.width * 25.4 / model.dpi
    paper = PAPER.get(model.paper, tr("thermal paper wider than the print width"))
    out = [(tr("Paper"), paper)]
    if model.labels:
        out.append((tr("Labels"), tr("die-cut labels supported")))
    return out + [(tr("Print width"), tr("{0:.1f} mm ({1} dots)", mm, model.width)),
                  (tr("Resolution"), tr("{0} dpi ({1:.0f} dots per mm)", model.dpi, model.dpi / 25.4))]


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
        paper=best["size"],
        labels=bool(best["canPrintLabel"]),
    )


def is_known(ble_name):
    return lookup(ble_name).name != "generic"
