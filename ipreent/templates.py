"""Templates: cute SVG designs (frames, hearts, lists, notes, tags) with text boxes you fill in.

A template is an ordinary SVG file. Extra attributes in the iPreent namespace (`urn:ipreent:template`,
prefix `ip:`) name it and mark invisible rectangles as text boxes; the art is drawn by resvg and the
text by our own text code, so it shrinks to fit, wraps, uses the bundled cute fonts and falls back to
emoji fonts. docs/TEMPLATES.md describes the format for anyone who wants to make their own.

    <svg viewBox="0 0 384 300" xmlns:ip="urn:ipreent:template" ip:name="Big heart" ip:category="love">
      ...art...
      <rect ip:field="message" ip:label="Message" ip:default="You make me smile" ip:font="script"
            ip:size="40" ip:min="18" x="90" y="90" width="204" height="110" fill="none"/>
    </svg>

`ip:stretch="Y"` on the root lets the design grow taller at height Y (the pixel row there is repeated)
when a text box that crosses Y needs more room than it has at its smallest font size; boxes below Y
move down. That is how lists and frames take any number of lines.

Built-in templates live in ipreent/templates/NN-id.svg (NN orders the gallery); the same files are in
android/app/src/main/assets/templates (a test keeps them identical). On a PC, SVG files dropped into
<config dir>/templates show up as "Mine".

Port: android/.../Templates.kt (same layout rules, same test cases in tests/test_templates.py).
"""
import io
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field as dfield, replace
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw

from . import config, imaging

NS = "urn:ipreent:template"
SVG_NS = "http://www.w3.org/2000/svg"
HERE = Path(__file__).parent / "templates"

# Gallery categories, in the order the filter chips show them. "mine" = the user's own SVG files.
CATEGORIES = {"love": "Love", "frames": "Frames", "lists": "Lists", "notes": "Notes", "party": "Party",
              "labels": "Labels", "mine": "Mine"}
FONTS = ("round", "script", "sans", "bold")
LISTS = ("none", "check", "dot", "heart")
LINE_HEIGHT = 1.25        # line pitch, in font sizes
CAP = 0.7                 # roughly the cap height of our fonts: lines are centred on it
MIN_PX = 8                # never smaller than this many dots, whatever the template says


def _half_up(v):
    """Round like Kotlin's Math.round (Python's round() goes to even)."""
    return math.floor(v + 0.5)


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    default: str
    x: float
    y: float
    w: float
    h: float
    font: str = "round"
    size: float = 32
    min: float = 14
    align: str = "center"     # center | left | right (lists are always left)
    valign: str = "middle"    # middle | top
    list: str = "none"        # none | check | dot | heart: a mark before every line you type
    lines: int = 0            # most lines allowed (0 = any); 1 also means a one-line text box in editors
    color: str = "black"      # black | white (white text for boxes on a black part of the art)

    @property
    def multiline(self):
        return self.lines != 1


@dataclass(frozen=True)
class Template:
    id: str
    name: str
    category: str
    width: float              # viewBox size
    height: float
    stretch: float | None
    fields: tuple
    svg: str = dfield(repr=False, compare=False)
    path: str = ""

    def defaults(self):
        return {f.key: f.default for f in self.fields}


class TemplateError(ValueError):
    pass


def _num(v, default=0.0):
    try:
        return float(re.match(r"\s*([-+]?[\d.]+(?:[eE][-+]?\d+)?)", v).group(1))
    except (TypeError, AttributeError, ValueError):
        return default


def _ip(el, name, default=None):
    return el.get(f"{{{NS}}}{name}", default)


def parse(svg, id="template", path=""):
    """Template from SVG text. Raises TemplateError if it isn't an SVG we can use."""
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as e:
        raise TemplateError(f"not a valid SVG file ({e})") from None
    if root.tag not in (f"{{{SVG_NS}}}svg", "svg"):
        raise TemplateError("not an SVG file")
    vb = (root.get("viewBox") or "").replace(",", " ").split()
    if len(vb) == 4 and _num(vb[2]) > 0 and _num(vb[3]) > 0:
        ox, oy, w, h = (_num(v) for v in vb)
    else:
        ox = oy = 0.0
        w, h = _num(root.get("width"), 384), _num(root.get("height"), 384)
        if w <= 0 or h <= 0:
            raise TemplateError("the SVG has no size (viewBox or width/height)")
    stretch = _ip(root, "stretch")
    stretch = _num(stretch) - oy if stretch is not None else None
    if stretch is not None and not 0 < stretch < h:
        stretch = None
    fields, seen = [], set()
    for el in root.iter():
        key = _ip(el, "field")
        if not key or key in seen:
            continue
        seen.add(key)
        font = _ip(el, "font", "round")
        mark = _ip(el, "list", "none")
        size = _num(_ip(el, "size"), 32)
        fields.append(Field(
            key=key, label=_ip(el, "label", key.capitalize()), default=_ip(el, "default", ""),
            x=_num(el.get("x")) - ox, y=_num(el.get("y")) - oy,
            w=_num(el.get("width")), h=_num(el.get("height")),
            font=font if font in FONTS else "round", size=size, min=min(size, _num(_ip(el, "min"), 14)),
            align=_ip(el, "align", "center") if _ip(el, "align") in ("left", "right") else "center",
            valign="top" if _ip(el, "valign") == "top" else "middle",
            list=mark if mark in LISTS else "none", lines=int(_num(_ip(el, "lines"), 0)),
            color="white" if _ip(el, "color") == "white" else "black"))
    category = _ip(root, "category", "mine")
    return Template(id=id, name=_ip(root, "name") or id.replace("-", " ").capitalize(),
                    category=category if category in CATEGORIES else "mine",
                    width=w, height=h, stretch=stretch, fields=tuple(f for f in fields if f.w > 0 and f.h > 0),
                    svg=svg, path=path)


def _id(path):
    """`10-big-heart.svg` → `big-heart` (the number only orders the gallery)."""
    return re.sub(r"^\d+-", "", Path(path).stem)


@lru_cache(maxsize=1)
def builtin():
    return tuple(parse(p.read_text(encoding="utf-8"), _id(p), str(p)) for p in sorted(HERE.glob("*.svg")))


def user_dir():
    return config._path().parent / "templates"


def mine():
    """The user's own SVG files from <config dir>/templates (unreadable ones are skipped)."""
    out = []
    for p in sorted(user_dir().glob("*.svg")) if user_dir().is_dir() else ():
        try:
            out.append(replace(parse(p.read_text(encoding="utf-8"), _id(p), str(p)), category="mine"))
        except (OSError, UnicodeDecodeError, TemplateError):
            continue
    return tuple(out)


def all_templates():
    return builtin() + mine()


def find(name, files=True):
    """A template by id (`big-heart`), by number in the gallery (`3`), or (files=True) an SVG file path."""
    p = Path(name)
    if files and name.lower().endswith(".svg") and p.is_file():
        return parse(p.read_text(encoding="utf-8"), _id(p), str(p))
    items = all_templates()
    if name.isdigit() and 1 <= int(name) <= len(items):
        return items[int(name) - 1]
    for t in items:
        if t.id == name.lower():
            return t
    close = [t.id for t in items if name.lower() in t.id]
    hint = f" Did you mean {', '.join(close[:3])}?" if close else ""
    raise TemplateError(f"no template called {name!r}.{hint} See the list with: ipreent template")


# ---- layout: the same rules (and test cases) as Templates.kt -----------------------------------

@dataclass(frozen=True)
class Line:
    text: str
    first: bool       # first line of a list item (gets the mark)


def wrap(text, width, measure, indent=0.0, items=False):
    """Greedy word wrap. measure(s) → width. List items (one per typed line) skip blank lines and are
    indented by `indent`; words too long for a line are split between characters."""
    out = []
    avail = max(1.0, width - indent)
    for para in text.split("\n"):
        words = para.split()
        if not words:
            if not items:
                out.append(Line("", True))
            continue
        first, cur = True, ""
        for word in words:
            trial = f"{cur} {word}" if cur else word
            if measure(trial) <= avail:
                cur = trial
                continue
            if cur:
                out.append(Line(cur, first))
                first = False
            cur = ""
            for ch in word:                  # a word wider than the line: split it
                if cur and measure(cur + ch) > avail:
                    out.append(Line(cur, first))
                    first = False
                    cur = ""
                cur += ch
        out.append(Line(cur, first))
    while out and not out[-1].text and not items:     # trailing empty lines take no room
        out.pop()
    return out


@dataclass(frozen=True)
class Fit:
    size: int
    lines: tuple
    height: float     # height the lines need
    fits: bool


def fit(text, w, h, size, minimum, measure, mark="none", lines=0):
    """Largest whole font size from `size` down to `minimum` at which `text` fits in w×h.
    measure(s, size) → width. Doesn't fit even at the minimum → that size, with fits=False."""
    size, minimum = max(MIN_PX, int(size)), max(MIN_PX, int(min(minimum, size)))
    for s in range(size, minimum - 1, -1):
        got = wrap(text, w, lambda t: measure(t, s), _indent(mark, s), mark != "none")
        need = len(got) * s * LINE_HEIGHT
        ok = need <= h + 0.5 and (lines <= 0 or len(got) <= lines)
        if ok or s == minimum:
            return Fit(s, tuple(got), need, ok)


def _indent(mark, size):
    return 0.0 if mark == "none" else float(_half_up(size * 1.1))


@dataclass(frozen=True)
class Text:
    text: str
    x: float
    baseline: float
    size: int
    font: str
    color: str


@dataclass(frozen=True)
class Mark:
    kind: str         # check | dot | heart
    cx: float
    cy: float
    size: float       # height of the mark
    color: str


@dataclass(frozen=True)
class Layout:
    width: int
    height: int
    art_height: int   # height of the art before stretching
    stretch_at: int   # pixel row repeated `extra` times (0 when not stretched)
    extra: int
    items: tuple      # Text and Mark, in drawing order


def layout(t, values, width, measure):
    """Where every line of text goes at `width` dots. values: field key → text (missing = default).
    measure(text, size, font) → width in dots."""
    scale = width / t.width
    art_h = max(1, _half_up(t.height * scale))
    sy = _half_up(t.stretch * scale) if t.stretch is not None else None
    placed = []
    for f in t.fields:
        text = values.get(f.key, f.default) if values is not None else f.default
        x, y, w, h = f.x * scale, f.y * scale, f.w * scale, f.h * scale
        got = fit(text, w, h, _half_up(f.size * scale), _half_up(f.min * scale),
                  lambda s, size, font=f.font: measure(s, size, font), f.list, f.lines)
        placed.append([f, got, x, y, w, h])
    extra = 0
    if sy is not None:
        for f, got, x, y, w, h in placed:
            if not got.fits and y < sy < y + h and (f.lines <= 0 or len(got.lines) <= f.lines):
                extra = max(extra, math.ceil(got.height - h))
        for p in placed:
            _, _, x, y, w, h = p
            if y < sy < y + h:
                p[5] = h + extra
            elif y >= sy:
                p[3] = y + extra
    items = []
    for f, got, x, y, w, h in placed:
        if not any(l.text for l in got.lines):
            continue
        s = got.size
        lh = s * LINE_HEIGHT
        lines = got.lines
        if f.lines > 0:
            lines = lines[:f.lines]
        top = y if f.valign == "top" else y + (h - len(lines) * lh) / 2
        indent = _indent(f.list, s)
        for i, line in enumerate(lines):
            base = top + i * lh + (lh + CAP * s) / 2
            if f.list != "none":
                if line.first:
                    items.append(Mark(f.list, x + indent * 0.4, base - CAP * s / 2, CAP * s, f.color))
                lx = x + indent
            elif f.align == "left":
                lx = x
            else:
                lw = measure(line.text, s, f.font)
                lx = x + (w - lw) / 2 if f.align == "center" else x + w - lw
            if line.text:
                items.append(Text(line.text, lx, base, s, f.font, f.color))
    return Layout(width, art_h + extra, art_h, sy if extra else 0, extra, tuple(items))


# ---- drawing -----------------------------------------------------------------------------------

def measure(text, size, font):
    return imaging.text_length(text, size, font)


def svg_image(svg, width, height):
    """The SVG's art at width×height on white, grayscale (L)."""
    try:
        import resvg_py
    except ImportError:
        raise TemplateError("templates need the resvg_py package: pip install resvg_py") from None
    try:
        png = resvg_py.svg_to_bytes(svg_string=svg, width=width, height=height,
                                    skip_system_fonts="<text" not in svg)   # loading fonts is slow
    except ValueError as e:
        raise TemplateError(f"can't draw this SVG ({e})") from None
    img = Image.open(io.BytesIO(png)).convert("RGBA")
    if img.size != (width, height):
        img = img.resize((width, height))
    return Image.alpha_composite(Image.new("RGBA", img.size, "white"), img).convert("L")


def stretched(img, at, extra):
    """img made `extra` rows taller by repeating row `at`."""
    if extra <= 0:
        return img
    out = Image.new("L", (img.width, img.height + extra), 255)
    out.paste(img.crop((0, 0, img.width, at)), (0, 0))
    out.paste(img.crop((0, at, img.width, at + 1)).resize((img.width, extra)), (0, at))
    out.paste(img.crop((0, at, img.width, img.height)), (0, at + extra))
    return out


def heart_points(cx, cy, size, n=40):
    """A heart `size` tall centred on (cx, cy) (the classic parametric curve)."""
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        x = 16 * math.sin(a) ** 3
        y = 13 * math.cos(a) - 5 * math.cos(2 * a) - 2 * math.cos(3 * a) - math.cos(4 * a)
        pts.append((cx + x * size / 32, cy - (y + 2.5) * size / 30))
    return pts


def draw_mark(draw, m):
    ink = 255 if m.color == "white" else 0
    r = m.size / 2
    if m.kind == "check":
        stroke = max(2, _half_up(m.size / 9))
        draw.rectangle((m.cx - r, m.cy - r, m.cx + r, m.cy + r), outline=ink, width=stroke)
    elif m.kind == "dot":
        d = m.size * 0.22
        draw.ellipse((m.cx - d, m.cy - d, m.cx + d, m.cy + d), fill=ink)
    elif m.kind == "heart":
        draw.polygon(heart_points(m.cx, m.cy, m.size * 0.85), fill=ink)


def render(t, values=None, width=384):
    """The filled-in template as a grayscale image `width` dots wide (print it sharp, not dithered)."""
    lay = layout(t, values, width, measure)
    img = stretched(svg_image(t.svg, width, lay.art_height), lay.stretch_at, lay.extra)
    draw = ImageDraw.Draw(img)
    for it in lay.items:
        if isinstance(it, Mark):
            draw_mark(draw, it)
        else:
            imaging.draw_text(draw, (it.x, it.baseline), it.text, it.size, it.font,
                              fill=255 if it.color == "white" else 0, anchor="ls")
    return img


def thumbnail(t, width=192):
    return render(t, None, width)
