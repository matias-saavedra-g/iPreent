"""Templates: layout rules (same cases as android/.../TemplatesTest.kt) and the built-in collection."""
from pathlib import Path

import pytest

from ipreent import templates as t

ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "android" / "app" / "src" / "main" / "assets"


def mono(s, size=10):
    """Fake font: every character is half the font size wide."""
    return len(s) * size * 0.5


SAMPLE = """<svg xmlns="http://www.w3.org/2000/svg" xmlns:ip="urn:ipreent:template" viewBox="0 0 200 100"
     ip:name="Sample" ip:category="notes" ip:stretch="50">
  <rect x="0" y="0" width="200" height="100" fill="none" stroke="#000"/>
  <rect ip:field="title" ip:default="Hi" ip:size="20" ip:min="10" ip:lines="1" x="10" y="5" width="180" height="30" fill="none"/>
  <rect ip:field="items" ip:label="Items" ip:default="a&#10;b" ip:list="check" ip:size="10" ip:min="10"
        ip:valign="top" x="10" y="40" width="180" height="30" fill="none"/>
  <rect ip:field="foot" ip:default="end" ip:size="10" ip:align="right" x="10" y="80" width="180" height="15" fill="none"/>
</svg>"""


# ---- shared cases (TemplatesTest.kt) -----------------------------------------------------------

def test_wrap_words_and_long_words():
    lines = t.wrap("the quick brown fox", 50, mono)          # 10 characters per line
    assert [l.text for l in lines] == ["the quick", "brown fox"]
    lines = t.wrap("abcdefghijklmnop", 50, mono)
    assert [l.text for l in lines] == ["abcdefghij", "klmnop"]
    assert [l.first for l in lines] == [True, False]


def test_wrap_keeps_blank_lines_except_in_lists():
    assert [l.text for l in t.wrap("a\n\nb\n", 50, mono)] == ["a", "", "b"]
    lines = t.wrap("one two three\n\nfour", 40, mono, indent=10, items=True)   # 6 characters per line
    assert [(l.text, l.first) for l in lines] == [("one", True), ("two", False), ("three", False), ("four", True)]


def test_fit_shrinks_until_it_fits():
    measure = lambda s, size: len(s) * size * 0.5
    f = t.fit("hello world", 100, 40, 30, 10, measure)
    # 19: "hello world" is 104.5 wide, so two lines that need 47.5 > 40; 18: one line 99 wide, 22.5 high
    assert (f.size, [l.text for l in f.lines], f.fits) == (18, ["hello world"], True)
    f = t.fit("hello world", 100, 10, 30, 12, measure)
    assert (f.size, f.fits, f.height) == (12, False, 15.0)
    assert t.fit("a b c", 100, 100, 30, 10, measure, lines=1).size == 30


def test_parse_reads_fields_and_stretch():
    tp = t.parse(SAMPLE, "sample")
    assert (tp.name, tp.category, tp.width, tp.height, tp.stretch) == ("Sample", "notes", 200, 100, 50)
    title, items, foot = tp.fields
    assert (title.key, title.label, title.lines, title.multiline) == ("title", "Title", 1, False)
    assert (items.default, items.list, items.valign) == ("a\nb", "check", "top")
    assert (foot.align, foot.font, foot.min) == ("right", "round", 10)
    assert tp.defaults() == {"title": "Hi", "items": "a\nb", "foot": "end"}


def test_layout_positions_and_stretch():
    tp = t.parse(SAMPLE, "sample")
    measure = lambda s, size, font: len(s) * size * 0.5
    lay = t.layout(tp, {"items": "a\nb\nc\nd"}, 400, measure)       # scale 2
    # items: 4 lines of 20 at size 20 need 100, box is 60 → 40 extra rows from row 100
    assert (lay.height, lay.art_height, lay.stretch_at, lay.extra) == (240, 200, 100, 40)
    texts = [i for i in lay.items if isinstance(i, t.Text)]
    marks = [i for i in lay.items if isinstance(i, t.Mark)]
    assert [x.text for x in texts] == ["Hi", "a", "b", "c", "d", "end"]
    hi, a, *_, end = texts
    # centred: x = 20 + (360 - 40) / 2; line box 50 high in a 60 box from 10: baseline 15 + (50 + 28) / 2
    assert (hi.size, hi.x, hi.baseline) == (40, 180.0, 54.0)
    # top-aligned list: indent round(20 * 1.1) = 22, baseline 80 + (25 + 14) / 2
    assert (a.size, a.x, a.baseline) == (20, 42.0, 99.5)
    assert len(marks) == 4 and marks[0].cx == pytest.approx(28.8) and marks[0].cy == pytest.approx(92.5)
    # right-aligned, its box moved down by the 40 extra rows: 160 + 40 + (30 - 25) / 2 + 19.5
    assert (end.x, end.baseline) == (350.0, 222.0)
    assert t.layout(tp, None, 400, measure).extra == 0               # defaults fit


def test_empty_fields_draw_nothing():
    tp = t.parse(SAMPLE, "sample")
    lay = t.layout(tp, {"title": "", "items": "", "foot": " "}, 200, lambda s, size, font: len(s) * size * 0.5)
    assert lay.items == () and lay.height == 100


# ---- Python only -------------------------------------------------------------------------------

def test_builtin_collection_is_complete_and_sane():
    items = t.builtin()
    assert len(items) >= 15
    assert len({x.id for x in items}) == len(items)
    used = {x.category for x in items}
    assert used <= set(t.CATEGORIES) - {"mine"} and len(used) >= 5
    for x in items:
        assert x.width == 384 and x.fields, x.id
        for f in x.fields:
            assert f.default.strip(), (x.id, f.key)
            assert 0 <= f.x and f.x + f.w <= x.width and 0 <= f.y and f.y + f.h <= x.height, (x.id, f.key)
        # the defaults fit without shrinking to the minimum or stretching
        lay = t.layout(x, None, 384, t.measure)
        assert lay.extra == 0, x.id


def test_android_has_the_same_templates_and_fonts():
    for p in sorted(t.HERE.glob("*.svg")):
        assert (ANDROID / "templates" / p.name).read_bytes() == p.read_bytes(), p.name
    assert sorted(p.name for p in (ANDROID / "templates").glob("*.svg")) == sorted(p.name for p in t.HERE.glob("*.svg"))
    for name in ("Fredoka-SemiBold.ttf", "Pacifico-Regular.ttf"):
        assert (ANDROID / "fonts" / name).read_bytes() == (t.imaging.FONTS / name).read_bytes()


def test_every_template_renders_at_the_paper_width():
    pytest.importorskip("resvg_py")
    for x in t.builtin():
        img = t.render(x, None, 384)
        assert img.width == 384 and img.mode == "L"
        assert img.getextrema()[0] == 0, x.id                     # something black was drawn


def test_long_lists_stretch_the_design():
    pytest.importorskip("resvg_py")
    todo = t.find("to-do")
    short = t.render(todo, {"items": "one"}, 384)
    long = t.render(todo, {"items": "\n".join(f"item {i}" for i in range(20))}, 384)
    assert long.height > short.height + 300


def test_find_by_id_number_and_file(tmp_path):
    first = t.builtin()[0]
    assert t.find(first.id) == first and t.find("1") == first
    p = tmp_path / "mine.svg"
    p.write_text(SAMPLE)
    assert t.find(str(p)).name == "Sample"
    with pytest.raises(t.TemplateError, match="heart"):
        t.find("hear")


def test_own_svgs_show_up_as_mine():
    t.user_dir().mkdir(parents=True)
    (t.user_dir() / "05-plain.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"/>')
    (t.user_dir() / "broken.svg").write_text("<svg")
    mine = t.mine()
    assert [(m.id, m.name, m.category, m.fields) for m in mine] == [("plain", "Plain", "mine", ())]
    assert t.all_templates()[-1].id == "plain"


def test_bad_files_raise_template_errors():
    for bad in ("not xml", "<html/>", '<svg xmlns="http://www.w3.org/2000/svg" width="0" height="0"/>'):
        with pytest.raises(t.TemplateError):
            t.parse(bad)


def test_cli_lists_and_previews(tmp_path, capsys):
    pytest.importorskip("resvg_py")
    from PIL import Image
    from ipreent import cli
    cli.main(["template"])
    assert "big-heart" in capsys.readouterr().out
    out = tmp_path / "todo.png"
    cli.main(["template", "to-do", "Hoy", "Leche\\nPan", "--preview", str(out)])
    assert Image.open(out).size[0] == 384
    with pytest.raises(SystemExit, match="KEY=TEXT"):
        cli.main(["template", "to-do", "--set", "nope=x", "--preview", str(out)])
