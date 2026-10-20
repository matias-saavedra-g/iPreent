"""Turn images and text into rows of 0/1 pixels at the printer's width."""
from PIL import Image, ImageDraw, ImageFont, ImageOps


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


def _font(size):
    for name in ("DejaVuSans.ttf", "arial.ttf", "Arial.ttf", "Helvetica.ttc", "segoeui.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def text_image(text, width, size=28, margin=4):
    font = _font(size)
    lines = []
    for para in text.splitlines() or [""]:
        words, cur = para.split(" "), ""
        for w in words:
            trial = f"{cur} {w}".strip()
            if font.getlength(trial) <= width - 2 * margin or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    line_h = int(size * 1.25)
    img = Image.new("L", (width, line_h * len(lines) + 2 * margin), 255)
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((margin, margin + i * line_h), line, font=font, fill=0)
    return img


# ---- desktop app extras (same options as the Android app) ------------------------------------

DITHERS = {"floyd": "Floyd–Steinberg", "atkinson": "Atkinson", "threshold": "Threshold (sharp)"}


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
    font = _font(round(width * 0.85))
    l, t, r, b = font.getbbox(text or " ")
    strip = Image.new("L", (r + 20, b + 4), 255)
    ImageDraw.Draw(strip).text((10, 0), text, font=font, fill=0)
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
