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
