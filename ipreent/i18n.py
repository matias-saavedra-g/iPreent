"""Language of the command line and the Windows app: the system's, or a choice kept in the config dir.

English is the source text and the fallback. Code writes `tr("English text {0}", value)`; if the current language has
a translation for exactly that text (ipreent/locales/<lang>.json), it is used, otherwise the English text is. A
missing file, a missing entry or a broken translation (wrong placeholders) can never break the program: it just
stays English.

The choice (`system`, `en`, `es`) is a debug setting (Windows: printer menu › Debug settings, CLI: `ipreent settings
language`), kept in `<config dir>/language.json`. The environment variable IPREENT_LANG overrides it (tests use it).
"""
import json
import locale
import os
import sys
from pathlib import Path

from . import config

SYSTEM = "system"
CHOICES = (SYSTEM, "en", "es")
DEFAULT = "en"
LOCALES = Path(__file__).with_name("locales")

_cache = {}


def reload():
    """Forget what was read (after the choice changed, or in tests)."""
    _cache.clear()


def choice():
    """What the user picked: `system` (default), `en` or `es`."""
    v = os.environ.get("IPREENT_LANG") or config.load_extra("language").get("language") or SYSTEM
    return v if v in CHOICES else SYSTEM


def set_choice(value):
    if value not in CHOICES:
        raise ValueError(f"language must be one of: {', '.join(CHOICES)}")
    if value == SYSTEM:
        config.save_extra("language", {})
    else:
        config.save_extra("language", {"language": value})
    reload()


def _windows_locale():
    import ctypes
    buf = ctypes.create_unicode_buffer(85)
    return buf.value if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, 85) else ""


def system_language():
    """Two-letter code of the system's language ("es", "en", "fr"...), "en" if it can't be told."""
    names = []
    try:
        if sys.platform == "win32":
            names.append(_windows_locale())
        else:
            for var in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"):
                names += [n for n in os.environ.get(var, "").split(":") if n]
            if sys.platform == "darwin" and not names:
                import subprocess
                names.append(subprocess.run(["defaults", "read", "-g", "AppleLocale"], capture_output=True,
                                            text=True, timeout=3).stdout.strip())
            names.append((locale.getlocale()[0] or ""))
    except Exception:
        pass
    for n in names:
        code = n.replace("-", "_").split("_")[0].split(".")[0].lower()
        if code.isalpha() and len(code) in (2, 3) and code not in ("c", "posix"):
            return code
    return DEFAULT


def language():
    """The language in use: the choice, or the system's. A language without a translation file is English."""
    if "language" not in _cache:
        c = choice()
        code = system_language() if c == SYSTEM else c
        _cache["language"] = code if code == DEFAULT or (LOCALES / f"{code}.json").exists() else DEFAULT
    return _cache["language"]


def _read(name):
    try:
        data = json.loads((LOCALES / name).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def catalog(lang=None):
    """{English text: translation} for [lang] (empty for English and for languages without a file)."""
    lang = lang or language()
    key = "catalog:" + lang
    if key not in _cache:
        _cache[key] = {} if lang == DEFAULT else _read(f"{lang}.json")
    return _cache[key]


def template_texts(template_id, lang=None):
    """Translated {"name": ..., "fields": {key: {"label": ..., "default": ...}}} of a built-in template, or {}."""
    lang = lang or language()
    key = "templates:" + lang
    if key not in _cache:
        _cache[key] = {} if lang == DEFAULT else _read(f"templates.{lang}.json")
    value = _cache[key].get(template_id)
    return value if isinstance(value, dict) else {}


def _fill(text, args):
    return text.format(*args) if args else text


def tr(text, *args):
    """[text] in the current language, with {0}, {1}… filled from [args]. Always works: falls back to English."""
    found = catalog().get(text)
    if isinstance(found, str) and found:
        try:
            return _fill(found, args)
        except (IndexError, KeyError, ValueError):
            pass
    return _fill(text, args)


def trn(one, other, n, *args):
    """Singular [one] when n == 1, else [other] (both English); translated as a pair in the catalog."""
    found = catalog().get(one)
    if isinstance(found, list) and len(found) == 2 and all(isinstance(s, str) and s for s in found):
        try:
            return _fill(found[0 if n == 1 else 1], args)
        except (IndexError, KeyError, ValueError):
            pass
    return _fill(one if n == 1 else other, args)


def language_name(value):
    """How a language or choice is shown (languages by their own names, so you can find yours)."""
    return {"en": "English", "es": "Español"}.get(value) or tr("System")


def describe():
    """The language in use for people: "Español (system)", "English (debug choice)"..."""
    how = tr("system") if choice() == SYSTEM else tr("debug choice")
    return f"{language_name(language())} ({how})"
