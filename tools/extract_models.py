"""Extract the printer model table from the decompiled vendor app (jadx output) into JSON.

Usage: python -I tools/extract_models.py <jadx>/sources/com/Utils/PrintModelUtils.java models.json
"""
import json
import re
import sys

CONSTS = {
    "AccessibilityNodeInfoCompat.EXTRA_DATA_TEXT_CHARACTER_LOCATION_ARG_MAX_LENGTH": 20000,
    "BannerConfig.LOOP_TIME": 3000,
    "Constants.CP_MAC_ROMAN": 10000,
    "Shape.MASTER_DPI": 576,
    "OS2WindowsMetricsTable.WEIGHT_CLASS_EXTRA_BOLD": 800,
    "OS2WindowsMetricsTable.WEIGHT_CLASS_LIGHT": 300,
    "PDLayoutAttributeObject.GLYPH_ORIENTATION_VERTICAL_ZERO_DEGREES": "0",
}
# The first 26 positional arguments are shared by every DataBean constructor.
FIELDS = ["modelNo", "model", "size", "paperSize", "printSize", "oneLength", "headName",
          "canChangeMTU", "dpi", "imgSpeed", "textSpeed", "mtu", "newCompress", "paperNum",
          "interval", "thinEnergy", "midEnergy", "darkEnergy", "textEnergy", "hasId", "useSPP",
          "newFormat", "canPrintLabel", "labelValue", "backPaperNum", "detectionValue"]


def value(tok):
    tok = tok.strip()
    if tok in CONSTS:
        return CONSTS[tok]
    if tok in ("true", "false"):
        return tok == "true"
    if tok.startswith('"'):
        return tok.strip('"')
    try:
        return int(tok)
    except ValueError:
        return float(tok.rstrip("d"))


def main(src, dst):
    text = open(src, encoding="utf-8").read()
    models = {}
    for m in re.finditer(r'new PrinterModel\.DataBean\(("[^"]*",[^)]*)\)', text):
        args = re.findall(r'"[^"]*"|[^,]+', m.group(1))
        entry = dict(zip(FIELDS, (value(a) for a in args[:len(FIELDS)])))
        # Several models are declared twice (variants); keep the first.
        models.setdefault(entry["modelNo"], entry)
    json.dump(sorted(models.values(), key=lambda e: e["modelNo"]), open(dst, "w"), indent=1)
    print(f"{len(models)} models -> {dst}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
