"""A millimetre ruler printed along the paper, for measuring things and for timing the printer on video.

Everything is drawn here as plain geometry (seven-segment digits, no fonts), so the PC and the phone
print exactly the same dots: android/.../Ruler.kt is a line-by-line port and both test suites check
the same numbers (tests/test_ruler.py ↔ RulerTest.kt).

Accuracy:
- Across the paper the head's dots are fixed: 8 per mm on the usual 58 mm printers (protocol.dots_per_mm).
- Along the paper each printed row moves the paper one motor step, nominally the same 1/8 mm. Every tick
  is placed at round(mm × rows per mm) on its own, so rounding never adds up along the ruler: each mark
  is within half a row (1/16 mm) of where it should be. What the motor really feeds per row can differ a
  little between printers; `measured` corrects it: print a 100 mm ruler, measure it with a good ruler,
  and pass what you read (98.5 means the paper moved 1.5 % less than nominal, so rows are spread out).

Timing on video: the "timing track" (two columns of blocks that switch every millimetre) and the big
centimetre numbers make it easy to read, frame by frame, how many millimetres came out between two
frames: speed = mm / (frame difference / frame rate).
"""
import math

from PIL import Image

from .protocol import dots_per_mm

DEFAULT_MM = 100
MIN_MM, MAX_MM = 10, 1000
DEFAULT_MEASURED = 100.0                  # what a printed 100 mm measured: 100 = no correction
MIN_MEASURED, MAX_MEASURED = 90.0, 110.0

# Seven segments: a top, b top right, c bottom right, d bottom, e bottom left, f top left, g middle.
SEGMENTS = ("abcdef", "bc", "abged", "abgcd", "fgbc", "afgcd", "afgedc", "abc", "abcdefg", "abcdfg")


def _half_up(v):
    """Round like Kotlin's Math.round (Python's round() goes to even)."""
    return math.floor(v + 0.5)


def clamp_length(mm):
    return min(MAX_MM, max(MIN_MM, int(mm)))


def clamp_measured(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return DEFAULT_MEASURED
    return DEFAULT_MEASURED if v != v else min(MAX_MEASURED, max(MIN_MEASURED, v))


def rows_per_mm(dpi, measured=DEFAULT_MEASURED):
    """Paper rows per real millimetre, after the feed correction."""
    return dots_per_mm(dpi) * 100.0 / clamp_measured(measured)


class _Canvas:
    def __init__(self, width, height):
        self.w, self.h = width, height
        self.px = [bytearray(width) for _ in range(height)]

    def fill(self, x0, y0, x1, y1):
        """Black rectangle [x0, x1) × [y0, y1), clipped to the canvas."""
        x0, x1 = max(0, x0), min(self.w, x1)
        for y in range(max(0, y0), min(self.h, y1)):
            if x1 > x0:
                self.px[y][x0:x1] = b"\x01" * (x1 - x0)

    def digit(self, d, x, y, w, h, s):
        segs = SEGMENTS[d]
        mid = y + (h - s) // 2
        half = y + h // 2
        if "a" in segs: self.fill(x, y, x + w, y + s)
        if "d" in segs: self.fill(x, y + h - s, x + w, y + h)
        if "g" in segs: self.fill(x, mid, x + w, mid + s)
        if "f" in segs: self.fill(x, y, x + s, half + s // 2)
        if "b" in segs: self.fill(x + w - s, y, x + w, half + s // 2)
        if "e" in segs: self.fill(x, half - s // 2, x + s, y + h)
        if "c" in segs: self.fill(x + w - s, half - s // 2, x + w, y + h)

    def number(self, n, cx, cy, w, h, s, gap):
        """n centred on (cx, cy)."""
        text = str(n)
        total = len(text) * w + (len(text) - 1) * gap
        x = cx - total // 2
        for i, ch in enumerate(text):
            self.digit(int(ch), x + i * (w + gap), cy - h // 2, w, h, s)


class Layout:
    """Where everything goes, in dots and rows. `scale` keeps the sizes in mm on 300 dpi printers."""

    def __init__(self, width, dpi, length_mm=DEFAULT_MM, measured=DEFAULT_MEASURED):
        self.width = width
        self.dpmm = dots_per_mm(dpi)
        self.length = clamp_length(length_mm)
        self.k = rows_per_mm(dpi, measured)
        s = self.dpmm / 8.0
        self.r = lambda v: max(1, _half_up(v * s))
        r = self.r
        self.thick = r(2)                           # every tick and line is 2 dots (1/4 mm) thick
        self.top = r(8)                             # the scale across the paper starts here
        self.origin = self.top + self.thick + r(48)  # row of the 0 mm line of the ruler along the paper
        self.bottom = r(64)                          # room for the last number, under the end line

    def tick(self, mm):
        """Top row of the tick at `mm` along the paper (each one rounded on its own)."""
        return self.origin + _half_up(mm * self.k)

    def height(self):
        return self.tick(self.length) + self.thick + self.bottom


def rows(width, dpi, length_mm=DEFAULT_MM, measured=DEFAULT_MEASURED):
    """The ruler as rows of 0/1 dots (1 = black), `width` dots wide."""
    lay = Layout(width, dpi, length_mm, measured)
    r, t, w = lay.r, lay.thick, width
    c = _Canvas(w, lay.height())

    # Across the paper: a baseline with a tick every mm (longer every 5 and 10), numbered in cm.
    y = lay.top
    c.fill(0, y, w, y + t)
    mm = 0
    while True:
        x = _half_up(mm * lay.dpmm)
        if x > w - 1:
            break
        x = min(x, w - t)
        long = r(32) if mm % 10 == 0 else r(20) if mm % 5 == 0 else r(12)
        c.fill(x, y + t, x + t, y + t + long)
        if mm % 10 == 0 and x + r(4) + r(10) <= w:
            c.digit(mm // 10 % 10, x + r(4), y + t + r(14), r(10), r(16), r(2))
        mm += 1

    # Along the paper: ticks on both edges, a full line at 0 and at the end, numbers every cm,
    # a dashed guide across at every cm and the timing track (blocks switching every mm).
    short, mid, long = r(24), r(40), r(64)
    track = (r(72), r(88))
    dw, dh, ds, gap = r(26), r(44), r(5), r(8)
    for mm in range(lay.length + 1):
        p = lay.tick(mm)
        if mm in (0, lay.length):
            c.fill(0, p, w, p + t)
        else:
            n = long if mm % 10 == 0 else mid if mm % 5 == 0 else short
            c.fill(0, p, n, p + t)
            c.fill(w - n, p, w, p + t)
        if mm < lay.length and mm % 2 == 0:
            q = lay.tick(mm + 1)
            c.fill(track[0], p, track[1], q)
            c.fill(w - track[1], p, w - track[0], q)
        if mm % 10 == 0:                            # the number sits just under its tick, like a tape measure
            c.number(mm // 10, w // 2, p + t + r(6) + dh // 2, dw, dh, ds, gap)
            if 0 < mm < lay.length:
                x0, x1 = track[1] + r(8), w - track[1] - r(8)
                for x in range(x0, x1, r(8)):
                    c.fill(x, p, min(x + r(4), x1), p + 1)
    return [list(row) for row in c.px]


def image(width, dpi, length_mm=DEFAULT_MM, measured=DEFAULT_MEASURED):
    """The ruler as a black-and-white PIL image ("L"), for the print and preview paths."""
    rs = rows(width, dpi, length_mm, measured)
    img = Image.new("L", (width, len(rs)), 255)
    img.putdata([0 if v else 255 for row in rs for v in row])
    return img
