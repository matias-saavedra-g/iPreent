"""Receipts: business header, products with quantity and price, total in Chilean pesos, barcode.

    r = Receipt("MT", "Av. Pajaritos 1234, Maipú", "industriasmt.cl",
                items=[Item("Empanada de pino", 2990, 2), Item("Café", 1800)])
    r.total            # 7780
    clp(r.total)       # '$7.780'
    img = r.image(384) # PIL image, ready for the printer

The receipt number is the print time (YYMMDDhhmmss), so it needs no counter, no storage and
no syncing between devices. The barcode (Code 128) holds that number. The Android app
(Receipt.kt) draws the same layout; keep them in step.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from PIL import Image, ImageDraw

from . import imaging

DEFAULT_FOOTER = "Thank you for your purchase!"


# ---- money -----------------------------------------------------------------------------------

def parse_price(value):
    """'$12.990', '12990', '12,990', '-1.000' → whole pesos (int).

    CLP has no cents, so dots and commas are thousands separators. A separator followed by
    only one or two digits at the end ('12990.50') is read as decimals and rounded.
    """
    if isinstance(value, bool):
        raise ValueError(f"not a price: {value!r}")
    if isinstance(value, (int, float, Decimal)):
        return _round(Decimal(str(value)))
    text = str(value).strip()
    neg = "-" in re.match(r"\D*", text).group()
    body = re.sub(r"[^\d.,]", "", text)
    if not re.search(r"\d", body):
        raise ValueError(f"not a price: {value!r}")
    cents = re.search(r"[.,](\d{1,2})$", body)
    whole = re.sub(r"\D", "", body[:cents.start()] if cents else body) or "0"
    amount = Decimal(whole) + (Decimal("0." + cents.group(1)) if cents else 0)
    return _round(-amount if neg else amount)


def parse_qty(value):
    """'2', '1,5', '1.5', 'x3', '' (= 1) → Decimal quantity above zero."""
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        q = Decimal(str(value))
    else:
        text = re.sub(r"[x×\s]", "", str(value or "").lower()).replace(",", ".")
        try:
            q = Decimal(text) if text else Decimal(1)
        except InvalidOperation:
            raise ValueError(f"not a quantity: {value!r}") from None
    if not q.is_finite() or q <= 0:
        raise ValueError(f"quantity must be more than zero: {value!r}")
    return q


def _round(d):
    return int(Decimal(d).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def clp(amount):
    """12990 → '$12.990', -1000 → '-$1.000' (Chilean style: dot for thousands, no decimals)."""
    return ("-" if amount < 0 else "") + "$" + f"{abs(int(amount)):,}".replace(",", ".")


def fmt_qty(q):
    """Decimal('2') → '2', Decimal('1.50') → '1,5'."""
    q = Decimal(q).normalize()
    text = f"{q:f}"
    return text.replace(".", ",")


# ---- the receipt -----------------------------------------------------------------------------

@dataclass
class Item:
    name: str
    price: int            # unit price, whole pesos (negative for a discount)
    qty: Decimal = Decimal(1)

    def __post_init__(self):
        self.name = str(self.name).strip()
        self.price = parse_price(self.price)
        self.qty = parse_qty(self.qty)

    @property
    def amount(self):
        return _round(self.qty * self.price)


@dataclass
class Receipt:
    business: str = ""
    address: str = ""
    url: str = ""
    items: list = field(default_factory=list)
    footer: str = DEFAULT_FOOTER
    number: str = ""          # empty: taken from the time (YYMMDDhhmmss)
    when: datetime = None     # empty: now

    def __post_init__(self):
        self.when = self.when or datetime.now()
        self.number = str(self.number or self.when.strftime("%y%m%d%H%M%S")).strip()
        self.items = [i for i in self.items if i.name]

    @property
    def total(self):
        return sum(i.amount for i in self.items)

    @property
    def count(self):
        """Units sold; with weighed products (1,5 kg) it counts lines instead."""
        if all(i.qty == i.qty.to_integral_value() for i in self.items):
            return int(sum(i.qty for i in self.items))
        return len(self.items)

    @classmethod
    def from_dict(cls, data):
        """{"business", "address", "url", "footer", "number", "items": [{"name", "price", "qty"}
        or ["name", price, qty]]}. Raises ValueError on bad input."""
        items = []
        for raw in data.get("items") or []:
            if isinstance(raw, dict):
                name, price, qty = raw.get("name", ""), raw.get("price"), raw.get("qty", raw.get("quantity", 1))
            elif isinstance(raw, (list, tuple)) and 2 <= len(raw) <= 3:
                name, price, qty = raw[0], raw[1], raw[2] if len(raw) > 2 else 1
            else:
                raise ValueError(f"bad item {raw!r}: use {{\"name\", \"price\", \"qty\"}}")
            if price is None:
                raise ValueError(f"item {name!r} has no price")
            items.append(Item(name, price, qty))
        r = cls(business=str(data.get("business") or ""), address=str(data.get("address") or ""),
                url=str(data.get("url") or ""), items=items,
                footer=str(data["footer"]) if data.get("footer") is not None else DEFAULT_FOOTER,
                number=str(data.get("number") or ""))
        if not r.items:
            raise ValueError("a receipt needs at least one product")
        imaging.code128(r.number)        # fails early on a number the barcode can't hold
        return r

    def image(self, width):
        return render(self, width)


# ---- drawing ---------------------------------------------------------------------------------

def _wrap(text, size, kind, max_w):
    """Lines that fit max_w pixels; very long words are cut."""
    if not str(text).strip():
        return []
    out = []
    for para in str(text).splitlines():
        cur = ""
        for word in para.split():
            trial = f"{cur} {word}" if cur else word
            if imaging.text_length(trial, size, kind) <= max_w:
                cur = trial
                continue
            if cur:
                out.append(cur)
            while len(word) > 1 and imaging.text_length(word, size, kind) > max_w:
                n = len(word) - 1
                while n > 1 and imaging.text_length(word[:n], size, kind) > max_w:
                    n -= 1
                out.append(word[:n])
                word = word[n:]
            cur = word
        if cur:
            out.append(cur)
    return out


class _Sheet:
    """Collects drawing steps while measuring height; draws them once the height is known."""

    def __init__(self, width):
        self.w, self.y, self.ops = width, 0, []

    def text(self, s, size, kind="mono", align="left", margin=0):
        tw = imaging.text_length(s, size, kind)
        x = {"left": margin, "center": (self.w - tw) / 2, "right": self.w - margin - tw}[align]
        y = self.y
        self.ops.append(lambda d: imaging.draw_text(d, (round(x), y), s, size, kind))
        return tw

    def rect(self, x0, y0, x1, y1):
        self.ops.append(lambda d: d.rectangle((x0, y0, x1, y1), fill=0))

    def image(self):
        img = Image.new("L", (self.w, max(1, self.y)), 255)
        d = ImageDraw.Draw(img)
        for op in self.ops:
            op(d)
        return img


def render(r, width):
    """The receipt as a grayscale picture at the paper width (print it sharp, no dithering)."""
    k = width / 384                      # sizes below are for 58 mm paper (384 dots)
    px = lambda v: max(1, round(v * k))  # noqa: E731
    m = px(6)                            # side margin
    body, small, big, title = px(22), px(19), px(34), px(40)
    lh = lambda size: round(size * 1.3)  # noqa: E731
    s = _Sheet(width)

    def dashed(gap_before=8, gap_after=12):
        s.y += px(gap_before)
        dash, gap, x, y = px(7), px(5), m, s.y
        while x < width - m:
            s.rect(x, y, min(x + dash, width - m) - 1, y + px(2) - 1)
            x += dash + gap
        s.y += px(2) + px(gap_after)

    def solid(thick=3, gap_before=8, gap_after=10):
        s.y += px(gap_before)
        s.rect(m, s.y, width - m - 1, s.y + px(thick) - 1)
        s.y += px(thick) + px(gap_after)

    def row(left, right, size, kind="mono"):
        s.text(left, size, kind, "left", m)
        s.text(right, size, kind, "right", m)
        s.y += lh(size)

    # Header: name big and bold, then address and website.
    s.y = px(10)
    for line in _wrap(r.business, title, "bold", width - 2 * m):
        s.text(line, title, "bold", "center")
        s.y += lh(title)
    if r.business.strip():
        s.y += px(4)
    for text in (r.address, r.url):
        for line in _wrap(text, small, "mono", width - 2 * m):
            s.text(line, small, "mono", "center")
            s.y += lh(small)

    dashed(gap_before=12)
    row(r.when.strftime("%d-%m-%Y"), r.when.strftime("%H:%M"), small)
    row("RECEIPT", f"N° {r.number}", small)
    dashed()

    # Products: name on the left (wrapped), amount on the right, "2 x $2.990" underneath.
    for it in r.items:
        amount = clp(it.amount)
        aw = imaging.text_length(amount, body, "mono")
        lines = _wrap(it.name, body, "mono", width - 2 * m - aw - px(14)) or [""]
        s.text(lines[0], body, "mono", "left", m)
        s.text(amount, body, "mono", "right", m)
        s.y += lh(body)
        for line in lines[1:]:
            s.text(line, body, "mono", "left", m)
            s.y += lh(body)
        if it.qty != 1:
            s.text(f"  {fmt_qty(it.qty)} x {clp(it.price)}", small, "mono", "left", m)
            s.y += lh(small)
        s.y += px(4)

    dashed(gap_before=4)
    row("Items", str(r.count), small)
    solid(gap_before=6)

    # Total: as big as fits.
    total = clp(r.total)
    size = big
    while size > body and imaging.text_length(f"TOTAL  {total}", size, "monobold") > width - 2 * m:
        size -= 1
    row("TOTAL", total, size, "monobold")
    solid(thick=2, gap_before=2, gap_after=0)
    solid(thick=2, gap_before=3, gap_after=0)

    # Footer and barcode.
    s.y += px(18)
    for line in _wrap(r.footer, px(24), "bold", width - 2 * m):
        s.text(line, px(24), "bold", "center")
        s.y += lh(px(24))
    s.y += px(14)
    mods = [0] * 10 + imaging.code128(r.number) + [0] * 10      # quiet zones
    scale = width // len(mods)
    if not scale:
        raise ValueError(f"receipt number too long for a barcode on this paper: {r.number}")
    left = (width - len(mods) * scale) // 2
    bar_h = px(64)
    for i, on in enumerate(mods):
        if on:
            s.rect(left + i * scale, s.y, left + (i + 1) * scale - 1, s.y + bar_h - 1)
    s.y += bar_h + px(6)
    s.text(r.number, small, "mono", "center")
    s.y += lh(small) + px(12)
    return s.image()
