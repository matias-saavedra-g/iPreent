"""Language support: system language, the debug choice, English fallback, and the Spanish catalog."""
import json
import re
from pathlib import Path

import pytest

from ipreent import cli, config, i18n, templates

LOCALES = Path(i18n.__file__).parent / "locales"
ANDROID_TEMPLATES = Path(__file__).parent.parent / "android/app/src/main/assets/i18n/templates.es.json"


@pytest.fixture
def lang(monkeypatch):
    """Switch the language for one test (the autouse fixture in conftest puts English back)."""
    def use(code):
        monkeypatch.setenv("IPREENT_LANG", code)
        i18n.reload()
        templates.builtin.cache_clear()
    yield use
    monkeypatch.setenv("IPREENT_LANG", "en")
    i18n.reload()
    templates.builtin.cache_clear()


def test_english_is_the_source_text():
    assert i18n.tr("Nothing to print.") == "Nothing to print."
    assert i18n.tr("Found {0} [{1}]", "SC03h", "AA:BB") == "Found SC03h [AA:BB]"
    assert i18n.trn("{0} product", "{0} products", 1, 1) == "1 product"
    assert i18n.trn("{0} product", "{0} products", 3, 3) == "3 products"
    assert i18n.tr("JSON: {\"a\": 1}") == 'JSON: {"a": 1}'        # no arguments: braces are left alone


def test_spanish_translates_and_untranslated_text_falls_back_to_english(lang):
    lang("es")
    assert i18n.language() == "es"
    assert i18n.tr("Nothing to print.") == "No hay nada que imprimir."
    assert i18n.tr("Found {0} [{1}]", "SC03h", "AA") == "Se encontró SC03h [AA]"
    assert i18n.trn("{0} product", "{0} products", 1, 1) == "1 producto"
    assert i18n.trn("{0} product", "{0} products", 2, 2) == "2 productos"
    assert i18n.tr("this sentence has no translation {0}", 5) == "this sentence has no translation 5"
    assert i18n.trn("one thing", "{0} things", 4, 4) == "4 things"


def test_a_broken_translation_never_breaks_the_program(lang, monkeypatch):
    lang("es")
    cat = dict(i18n.catalog())
    cat["Found {0} [{1}]"] = "Se encontró {0} {2}"                # wrong placeholder
    cat["Nothing to print."] = ""                                  # empty
    cat["{0} product"] = ["solo uno"]                              # not a pair
    monkeypatch.setitem(i18n._cache, "catalog:es", cat)
    assert i18n.tr("Found {0} [{1}]", "A", "B") == "Found A [B]"
    assert i18n.tr("Nothing to print.") == "Nothing to print."
    assert i18n.trn("{0} product", "{0} products", 2, 2) == "2 products"


def test_a_missing_or_unreadable_catalog_is_english(lang, monkeypatch, tmp_path):
    lang("en")
    monkeypatch.setattr(i18n, "LOCALES", tmp_path)
    (tmp_path / "es.json").write_text("not json", encoding="utf-8")
    monkeypatch.setenv("IPREENT_LANG", "es")
    i18n.reload()
    assert i18n.catalog("es") == {}
    assert i18n.tr("Nothing to print.") == "Nothing to print."
    assert i18n.language() == "es"
    (tmp_path / "es.json").unlink()
    i18n.reload()
    assert i18n.language() == "en"                                 # no file: English


def test_system_language_is_used_unless_a_choice_was_made(monkeypatch):
    monkeypatch.delenv("IPREENT_LANG")
    for var in ("LC_ALL", "LC_MESSAGES", "LANGUAGE"):
        monkeypatch.delenv(var, raising=False)
    for value, expected in [("es_CL.UTF-8", "es"), ("es_ES", "es"), ("en_US.UTF-8", "en"), ("fr_FR.UTF-8", "en"),
                            ("C", "en"), ("", "en")]:
        monkeypatch.setenv("LANG", value)
        i18n.reload()
        assert i18n.language() == expected, value
    monkeypatch.setenv("LANGUAGE", "es:en")                       # a list: the first one counts
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    i18n.reload()
    assert i18n.language() == "es"

    i18n.set_choice("en")                                         # the debug choice beats the system
    assert (i18n.choice(), i18n.language()) == ("en", "en")
    i18n.set_choice("es")
    assert (i18n.choice(), i18n.language()) == ("es", "es")
    assert config.load_extra("language") == {"language": "es"}
    i18n.set_choice("system")
    assert i18n.choice() == "system" and config.load_extra("language") == {}
    with pytest.raises(ValueError):
        i18n.set_choice("klingon")
    monkeypatch.setenv("IPREENT_LANG", "en")


def test_the_cli_can_set_the_language(capsys, monkeypatch):
    monkeypatch.delenv("IPREENT_LANG")
    cli.main(["settings", "language", "es"])
    assert "Español" in capsys.readouterr().out and i18n.choice() == "es"
    cli.main(["settings"])
    out = capsys.readouterr().out
    assert "Ajustes (cambia con" in out and "Español (elección de depuración)" in out
    cli.main(["settings", "language", "system"])
    assert i18n.choice() == "system"
    with pytest.raises(SystemExit):
        cli.main(["settings", "language", "klingon"])
    monkeypatch.setenv("IPREENT_LANG", "en")


def test_spanish_cli_output(lang, capsys):
    lang("es")
    cli.main([])
    out = capsys.readouterr().out
    assert "controlador sin conexión" in out and "Más usados" in out


def _placeholders(text):
    return sorted(re.findall(r"\{\d+[^}]*\}|%\(\w+\)\w|%[sd]", text))


def test_spanish_catalog_keeps_every_placeholder():
    cat = json.loads((LOCALES / "es.json").read_text(encoding="utf-8"))
    assert len(cat) > 300
    for key, value in cat.items():
        if isinstance(value, list):
            assert len(value) == 2 and all(isinstance(v, str) and v for v in value), key
            for v in value:
                assert [p.split(":")[0].split("!")[0] for p in _placeholders(v)] == \
                       [p.split(":")[0].split("!")[0] for p in _placeholders(key)] or _placeholders(v), key
        else:
            assert isinstance(value, str) and value.strip(), key
            assert [re.sub(r"[:!].*\}", "}", p) for p in _placeholders(value)] == \
                   [re.sub(r"[:!].*\}", "}", p) for p in _placeholders(key)], key


def test_every_text_in_the_code_works_in_spanish(lang):
    """Each tr()/trn() literal in the program renders (with dummy arguments) in Spanish without errors."""
    import ast
    lang("es")
    cat = i18n.catalog()
    for f in list(Path(i18n.__file__).parent.glob("*.py")) + list(Path(i18n.__file__).parent.glob("desktop/*.py")):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") in ("tr", "trn") and n.args and \
                    isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                key = n.args[0].value
                args = [1] * len(set(re.findall(r"\{(\d+)", key)))        # an int fits every format used
                if n.func.id == "tr":
                    assert i18n.tr(key, *args)
                if key in cat:
                    assert cat[key], (f.name, key)


def test_spanish_templates(lang):
    lang("es")
    t = {x.id: x for x in templates.builtin()}
    assert t["big-heart"].name == "Corazón grande"
    assert t["big-heart"].fields[0].label == "Mensaje" and t["big-heart"].fields[0].default == "Haces sonreír a mi corazón"
    assert t["letter-to-santa"].fields[0].default == "Querido Viejito Pascuero"      # not translated: kept
    assert templates.category_name("love") == "Amor" and templates.CATEGORIES["love"] == "Love"
    lang("en")
    assert {x.id: x for x in templates.builtin()}["big-heart"].name == "Big heart"


def test_template_translations_name_real_templates_and_boxes():
    tr = json.loads((LOCALES / "templates.es.json").read_text(encoding="utf-8"))
    real = {t.id: {f.key for f in t.fields} for t in templates.builtin()}
    for tid, texts in tr.items():
        assert tid in real, tid
        assert set(texts.get("fields", {})) <= real[tid], tid


def test_android_has_the_same_template_translations():
    assert ANDROID_TEMPLATES.read_bytes() == (LOCALES / "templates.es.json").read_bytes()
