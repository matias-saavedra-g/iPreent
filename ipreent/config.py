"""Remembers the last printer used, so later runs connect without scanning."""
import json
import os
import sys
from pathlib import Path


def _path():
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "ipreent" / "config.json"


def load():
    try:
        return json.loads(_path().read_text())
    except (OSError, ValueError):
        return {}


def save(**values):
    cfg = load()
    cfg.update({k: v for k, v in values.items() if v is not None})
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=1))
    return cfg


def forget():
    try:
        _path().unlink()
    except OSError:
        pass


def _extra(name):
    return _path().with_name(f"{name}.json")


def load_extra(name):
    """Other remembered settings (e.g. the receipt's business details), kept apart from the printer."""
    try:
        return json.loads(_extra(name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_extra(name, data):
    p = _extra(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
