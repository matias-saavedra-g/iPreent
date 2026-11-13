"""Turn images and text into rows of 0/1 pixels at the printer's width."""
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .i18n import tr

FONTS = Path(__file__).parent / "fonts"      # bundled, SIL Open Font License (see the OFL-*.txt there)


def image_rows(img, width, dither=True, threshold=128, auto_rotate=True):
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, "white")
        img = Image.alpha_composite(bg, img)
    img = img.convert("L")
    if auto_rotate and img.width > img.height * 1.3:   # landscape: rotate to use the full paper width
        img = img.rotate(90, expand=True)
    h = max(1, round(img.height * width / img.width))
    img = img.resize((width, h), Image.LANCZOS)
    if dither:
        bw = img.convert("1")          # Floyd-Steinberg
    else:
        bw = img.point(lambda p: 255 if p >= threshold else 0, "1")
    px = bw.load()
    return [[0 if px[x, y] else 1 for x in range(width)] for y in range(bw.height)]


# Font faces by kind: Windows, Linux, macOS names. "mono" gives receipts their classic look.
FACES = {
    "sans": ("DejaVuSans.ttf", "arial.ttf", "Arial.ttf", "Helvetica.ttc", "segoeui.ttf"),
    "bold": ("DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf", "segoeuib.ttf", "DejaVuSans.ttf"),
    "mono": ("DejaVuSansMono.ttf", "consola.ttf", "Menlo.ttc", "cour.ttf", "Courier New.ttf"),
    "monobold": ("DejaVuSansMono-Bold.ttf", "consolab.ttf", "courbd.ttf", "Courier New Bold.ttf",
                 "DejaVuSansMono.ttf", "consola.ttf"),
    # Bundled with iPreent for templates, so they look the same on every computer and phone.
    "round": (str(FONTS / "Fredoka-SemiBold.ttf"),),
    "script": (str(FONTS / "Pacifico-Regular.ttf"),),
}


@lru_cache(maxsize=64)
def _font(size, kind="sans"):
    for name in FACES[kind] + FACES["sans"]:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


# Tried in order for characters the main font lacks: emoji (Segoe UI Emoji's plain outlines are
# black and white, which suits thermal paper), symbols, then Chinese/Japanese/Korean and Indic.
FALLBACKS = ("seguiemj.ttf", "NotoEmoji-Regular.ttf", "seguisym.ttf", "msyh.ttc", "YuGothR.ttc",
             "malgun.ttf", "Nirmala.ttf", "NotoSansCJK-Regular.ttc", "DejaVuSans.ttf")
JOINERS = "‍️⃣"    # zero-width joiner, emoji style, keycap


@lru_cache(maxsize=32)
def _fallbacks(size):
    fonts = []
    for name in FALLBACKS:
        try:
            fonts.append(ImageFont.truetype(name, size))
        except OSError:
            continue
    return tuple(fonts)


@lru_cache(maxsize=4096)
def _has_glyph(font, ch):
    """False when the font would draw its "missing glyph" box for ch."""
    def mask(c):
        m = font.getmask(c)
        return m.size, bytes(m)
    return ch.isspace() or mask(ch) != mask("􏿽")


def _is_emoji(ch):
    c = ord(ch)
    return (c >= 0x1F000 or 0x2190 <= c <= 0x21FF or 0x2300 <= c <= 0x23FF or 0x25A0 <= c <= 0x27BF
            or 0x2B00 <= c <= 0x2BFF or c in (0x00A9, 0x00AE, 0x2122))


def _runs(text, size, kind="sans"):
    """Split text into [piece, font] runs, each character in the first font that has it."""
    main, extra = _font(size, kind), _fallbacks(size)
    runs = []
    for ch in text:
        if ch in JOINERS and runs:
            f = runs[-1][1]                      # joiners stay with the emoji they belong to
            if ch == "⃣" or (ch == "️" and f is main):
                # keycap 1️⃣ or text-style symbol made emoji: move the base character over
                f = next((e for e in extra if _has_glyph(e, "⃣")), f)
                if f is not runs[-1][1]:
                    base = runs[-1][0][-1]
                    runs[-1][0] = runs[-1][0][:-1]
                    if not runs[-1][0]:
                        runs.pop()
                    ch = base + ch
        else:
            order = (*extra, main) if _is_emoji(ch) else (main, *extra)
            f = next((o for o in order if _has_glyph(o, ch)), main)
        if runs and runs[-1][1] is f:
            runs[-1][0] += ch
        else:
            runs.append([ch, f])
    return runs


def text_length(text, size, kind="sans"):
    return sum(f.getlength(t) for t, f in _runs(text, size, kind))


def draw_text(draw, xy, text, size, kind="sans", fill=0, anchor="la"):
    """Text at xy (top-left by default; anchor "ls" puts xy on the baseline), emoji from fallback fonts."""
    x, y = xy
    for t, f in _runs(text, size, kind):
        draw.text((x, y), t, font=f, fill=fill, anchor=anchor)
        x += f.getlength(t)


def text_image(text, width, size=28, margin=4):
    lines = []
    for para in text.splitlines() or [""]:
        words, cur = para.split(" "), ""
        for w in words:
            trial = f"{cur} {w}".strip()
            if text_length(trial, size) <= width - 2 * margin or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    line_h = int(size * 1.25)
    img = Image.new("L", (width, line_h * len(lines) + 2 * margin), 255)
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw_text(draw, (margin, margin + i * line_h), line, size)
    return img


# ---- desktop app extras (same options as the Android app) ------------------------------------

DITHERS = {"floyd": "Floyd–Steinberg", "atkinson": "Atkinson", "threshold": tr("Threshold (sharp)")}


def gray(img, width, auto_rotate=True, brightness=0.0, contrast=1.0):
    """Grayscale image at the paper width. brightness -1..1, contrast around 1."""
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        img = Image.alpha_composite(Image.new("RGBA", img.size, "white"), img)
    img = img.convert("L")
    if auto_rotate and img.width > img.height * 1.3:
        img = img.rotate(90, expand=True)
    h = max(1, round(img.height * width / img.width))
    img = img.resize((width, h), Image.LANCZOS)
    if brightness or contrast != 1.0:
        img = img.point(lambda p: max(0, min(255, round((p - 128) * contrast + 128 + brightness * 255))))
    return img


def bw_rows(g, method="floyd", threshold=128):
    """Grayscale image → rows of 0/1 (1 = black)."""
    w, h = g.size
    if method == "floyd":
        px = g.convert("1").load()
        return [[0 if px[x, y] else 1 for x in range(w)] for y in range(h)]
    if method == "threshold":
        data = g.tobytes()
        return [[1 if data[y * w + x] < threshold else 0 for x in range(w)] for y in range(h)]
    # Atkinson: spreads 6/8 of the error, so highlights stay clean (nicer on thermal paper).
    data = g.tobytes()
    rows = []
    nxt, nxt2 = [0.0] * (w + 2), [0.0] * (w + 2)
    for y in range(h):
        cur = [data[y * w + x] + nxt[x] for x in range(w)] + [0.0, 0.0]
        nxt, nxt2 = nxt2, [0.0] * (w + 2)
        row = [0] * w
        for x in range(w):
            old = cur[x]
            black = old < threshold
            row[x] = 1 if black else 0
            e = (old - (0 if black else 255)) / 8
            if e:
                cur[x + 1] += e
                cur[x + 2] += e
                if x:
                    nxt[x - 1] += e
                nxt[x] += e
                nxt[x + 1] += e
                nxt2[x] += e
        rows.append(row)
    return rows


def trim(img, pad=8, threshold=245):
    """Crop white margins (for full pages from the Windows print dialog). None if blank."""
    g = img.convert("L")
    box = g.point(lambda p: 255 if p < threshold else 0).getbbox()
    if not box:
        return None
    l, t, r, b = box
    return img.crop((max(0, l - pad), max(0, t - pad), min(img.width, r + pad), min(img.height, b + pad)))


def checklist_image(title, items, width, size=28):
    head = text_image(title, width, size=round(size * 1.3)) if title.strip() else None
    box = size
    parts = [text_image(i, width - box - 16, size=size) for i in items if i.strip()]
    h = (head.height if head else 0) + sum(max(p.height, box + 8) + 4 for p in parts)
    img = Image.new("L", (width, max(1, h)), 255)
    d = ImageDraw.Draw(img)
    y = 0
    if head:
        img.paste(head, (0, 0))
        y = head.height
    for p in parts:
        d.rectangle((6, y + 6, 6 + box - 4, y + box + 2), outline=0, width=3)
        img.paste(p, (box + 12, y))
        y += max(p.height, box + 8) + 4
    return img


def banner_image(text, width):
    """Huge text running along the paper (rotated 90°)."""
    size = round(width * 0.85)
    b = max(f.getbbox(t)[3] for t, f in _runs(text or " ", size))
    strip = Image.new("L", (round(text_length(text or " ", size)) + 20, b + 4), 255)
    draw_text(ImageDraw.Draw(strip), (10, 0), text, size)
    strip = strip.rotate(-90, expand=True)
    img = Image.new("L", (width, strip.height), 255)
    img.paste(strip, ((width - strip.width) // 2, 0))
    return img


def qr_image(content, width):
    import segno
    qr = segno.make(content or " ", error="m")
    n = qr.symbol_size(border=1)[0]
    scale = max(1, (width * 3 // 4) // n)
    img = Image.new("L", (width, n * scale + 16), 255)
    mat = list(qr.matrix_iter(scale=scale, border=1))
    left = (width - n * scale) // 2
    px = img.load()
    for y, row in enumerate(mat):
        for x, v in enumerate(row):
            if v:
                px[left + x, 8 + y] = 0
    return img


# Code 128: bar/space widths for values 0..105, then the stop pattern.
_C128 = ("212222 222122 222221 121223 121322 131222 122213 122312 132212 221213 221312 231212 112232 "
         "122132 122231 113222 123122 123221 223211 221132 221231 213212 223112 312131 311222 321122 "
         "321221 312212 322112 322211 212123 212321 232121 111323 131123 131321 112313 132113 132311 "
         "211313 231113 231311 112133 112331 132131 113123 113321 133121 313121 211331 231131 213113 "
         "213311 213131 311123 311321 331121 312113 312311 332111 314111 221411 431111 111224 111422 "
         "121124 121421 141122 141221 112214 112412 122114 122411 142112 142211 241211 221114 413111 "
         "241112 134111 111242 121142 121241 114212 124112 124211 411212 421112 421211 212141 214121 "
         "412121 111143 111341 131141 114113 114311 411113 411311 113141 114131 311141 411131 211412 "
         "211214 211232").split()
_C128_STOP = "2331112"


def code128(data):
    """Module pattern (list of 0/1, 1 = bar) for data in Code 128 (set C for digits, else set B)."""
    if not data:
        raise ValueError(tr("nothing to encode"))
    if any(not 32 <= ord(c) < 127 for c in data):
        raise ValueError(tr("barcodes can only hold plain ASCII letters, digits and symbols"))
    if data.isdigit() and len(data) % 2 == 0:
        values = [105] + [int(data[i:i + 2]) for i in range(0, len(data), 2)]
    else:
        values = [104] + [ord(c) - 32 for c in data]
    values.append((values[0] + sum(i * v for i, v in enumerate(values[1:], 1))) % 103)
    mods = []
    for widths in [_C128[v] for v in values] + [_C128_STOP]:
        for i, w in enumerate(widths):
            mods += [1 if i % 2 == 0 else 0] * int(w)
    return mods


def barcode_image(data, width, height=96, size=24):
    """Code 128 barcode as wide as the paper allows, with the text underneath."""
    mods = [0] * 10 + code128(data) + [0] * 10           # quiet zones
    scale = width // len(mods)
    if scale < 1:
        raise ValueError(tr("too long for this paper ({0} characters)", len(data)))
    left = (width - len(mods) * scale) // 2
    label = text_image(data, width, size=size)
    img = Image.new("L", (width, height + label.height + 16), 255)
    d = ImageDraw.Draw(img)
    for i, m in enumerate(mods):
        if m:
            d.rectangle((left + i * scale, 8, left + (i + 1) * scale - 1, 8 + height), fill=0)
    tw = round(text_length(data, size))
    img.paste(label.crop((4, 0, min(width, tw + 8), label.height)), (max(0, (width - tw) // 2 - 4), height + 12))
    return img
