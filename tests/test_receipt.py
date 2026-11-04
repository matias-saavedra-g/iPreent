import json
from datetime import datetime
from decimal import Decimal

import pytest

from ipreent import cli, receipt
from ipreent.receipt import Item, Receipt, clp, fmt_qty, parse_price, parse_qty


def test_prices_are_whole_chilean_pesos():
    assert [parse_price(v) for v in ("$12.990", "12990", "12,990", "1.234.567", 2990)] == \
        [12990, 12990, 12990, 1234567, 2990]
    assert parse_price("-1.000") == -1000 and parse_price("$ -500") == -500
    assert parse_price("12990.50") == 12991 and parse_price("12990.4") == 12990   # decimals rounded
    with pytest.raises(ValueError):
        parse_price("abc")


def test_quantities():
    assert parse_qty("1,5") == Decimal("1.5") and parse_qty("") == 1 and parse_qty("x3") == 3
    assert fmt_qty(Decimal("1.50")) == "1,5" and fmt_qty(Decimal("2.0")) == "2"
    for bad in ("0", "-1", "lots"):
        with pytest.raises(ValueError):
            parse_qty(bad)


def test_clp_format():
    assert clp(12990) == "$12.990" and clp(-1000) == "-$1.000" and clp(0) == "$0"
    assert clp(1234567) == "$1.234.567"


def test_totals_and_number():
    r = Receipt("MT", items=[Item("Empanada", "2.990", 2), Item("Queso", "12.990", "0,35"),
                             Item("", 100), Item("Descuento", "-2.000")],
                when=datetime(2026, 11, 4, 15, 30, 12))
    assert r.total == 5980 + 4547 - 2000          # 0,35 x 12.990 = 4546,5 → 4547
    assert r.count == 3 and len(r.items) == 3     # weighed item: counts lines; empty name dropped
    assert r.number == "261104153012"
    assert Receipt(items=[Item("a", 1, 2), Item("b", 1, 3)]).count == 5


@pytest.mark.parametrize("width", [384, 576])
def test_image_fits_paper_and_grows_with_items(width):
    one = Receipt("Shop", "Street 1", "shop.cl", [Item("Coffee", 1800)]).image(width)
    many = Receipt("Shop", "Street 1", "shop.cl", [Item(f"Item {i}", 1000) for i in range(10)]).image(width)
    assert one.width == many.width == width and many.height > one.height
    long_name = Receipt(items=[Item("x" * 200, 1)]).image(width)    # cut, not overflowing
    assert long_name.width == width


def test_from_dict_and_errors():
    r = Receipt.from_dict({"business": "MT", "items": [{"name": "Café", "price": "1.800", "qty": 2},
                                                       ["Pan", 500]]})
    assert r.total == 4100 and r.footer == receipt.DEFAULT_FOOTER
    with pytest.raises(ValueError):
        Receipt.from_dict({"items": []})
    with pytest.raises(ValueError):
        Receipt.from_dict({"items": [{"name": "x"}]})
    with pytest.raises(ValueError):
        Receipt.from_dict({"items": [["x", 1]], "number": "café"})       # barcode is ASCII only


def test_cli_preview_remembers_business(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    out = tmp_path / "r.png"
    cli.main(["receipt", "-b", "Industrias MT", "--addr", "Maipú", "-i", "Café", "1.800", "2",
              "--preview", str(out), "-m", "SC03h"])
    assert out.exists()
    saved = json.loads((tmp_path / "ipreent" / "receipt.json").read_text(encoding="utf-8"))
    assert saved["business"] == "Industrias MT" and saved["address"] == "Maipú"
    csv = tmp_path / "p.csv"
    csv.write_text('name,price,qty\nPan,1.200,3\n"Bebida 1,5L","2.490"\n', encoding="utf-8")
    ns = type("A", (), dict(json=None, items_file=str(csv), item=None, business=None, biz_address=None,
                            url=None, footer=None, number=None))()
    r = cli._receipt(ns)
    assert r.business == "Industrias MT" and r.total == 3600 + 2490
