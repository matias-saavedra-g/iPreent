"""ipreent: print to iPrint-style thermal mini printers. No app, no account, no internet.

Examples:
  ipreent scan                       find printers
  ipreent print photo.jpg doc.pdf    print any image / PDF / text file
  ipreent text "Hello"               print text (or: echo hi | ipreent text)
  ipreent status                     paper, battery
  ipreent receipt -b "My shop" -i "Coffee" 1800 -i "Empanada" 2990 2
The printer used last is remembered; `ipreent forget` clears it.
"""
import argparse
import asyncio
import csv
import json
import sys

from PIL import Image

from . import api, config, convert, imaging, protocol, receipt
from .models import lookup


ENERGY_PRESETS = {"lightest": 5000, "lighter": 6000, "normal": 8000, "darker": 12000, "darkest": 17000}
DEFAULT_ENERGY = ENERGY_PRESETS["normal"]


def _energy(v):
    if v.lower() in ENERGY_PRESETS:
        return ENERGY_PRESETS[v.lower()]
    try:
        return int(v)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected a number or one of: {', '.join(ENERGY_PRESETS)}") from None


def _target(args):
    return api.Target(
        address=args.address or "", port=args.port or "", rfcomm=args.rfcomm or "",
        model=args.model or "", ble=args.ble,
        overrides={"width": args.width, "energy": args.energy or DEFAULT_ENERGY, "rle": args.rle,
                   "img_speed": args.speed, "text_speed": args.speed},
    )


def _offline_model(args):
    """Best guess at the model without connecting (for preview)."""
    return lookup(args.model or config.load().get("model") or config.load().get("name", ""))


def _progress(done, total):
    print(f"\r  sending {100 * done // total:3d}%", end="" if done < total else "\n",
          file=sys.stderr, flush=True)


def _parse_pages(spec):
    if not spec:
        return None
    pages = set()
    for part in spec.split(","):
        a, _, b = part.partition("-")
        pages.update(range(int(a), int(b or a) + 1))
    return pages


async def _print_items(args, make_items):
    async with api.connect(_target(args)) as p:
        items = make_items(p.model.width)
        rows, mode = api.rows_for(items, p.model.width, dither=not getattr(args, "no_dither", False))
        if not rows:
            sys.exit("Nothing to print.")
        print(f"{p.model.name}: {len(rows)} lines x{args.copies}", file=sys.stderr)
        await api.print_rows(p, rows, mode, args.copies, _progress, feed=args.feed)
        st = await p.request(protocol.CMD_GET_STATE)
        print("Printer:", protocol.describe_state(st) if st else "done", file=sys.stderr)


async def cmd_scan(args):
    found = await api.discover(args.timeout)
    if not found:
        print("No printers found. Is it on, and disconnected from the phone app?")
    for name, addr, m in found:
        link = "Bluetooth serial (pair it first)" if m.use_spp else "Bluetooth LE"
        print(f"{addr}  {name:<20} model={m.name:<10} {m.width} dots  {link}")


async def cmd_print(args):
    pages = _parse_pages(args.pages)

    def items(width):
        out = []
        for path in args.files:
            if path == "-":
                out.append((imaging.text_image(sys.stdin.read(), width, args.size), True))
            else:
                out += list(convert.to_images(path, width, args.size, pages))
        return out
    await _print_items(args, items)


async def cmd_text(args):
    text = " ".join(args.text) if args.text else sys.stdin.read()
    await _print_items(args, lambda w: [(imaging.text_image(text, w, args.size), True)])


RECEIPT_HEADER = ("business", "address", "url", "footer")
RECEIPT_FLAGS = {"business": "business", "address": "biz_address", "url": "url", "footer": "footer"}


def _receipt(args):
    """Receipt from (lowest first) the remembered business details, --json, --items-file, flags."""
    data = dict(config.load_extra("receipt"))
    data.setdefault("footer", receipt.DEFAULT_FOOTER)
    data["items"] = []
    if args.json:
        src = sys.stdin.read() if args.json == "-" else open(args.json, encoding="utf-8").read()
        loaded = json.loads(src)
        data.update({k: v for k, v in loaded.items() if k != "items"})
        data["items"] += loaded.get("items") or []
    if args.items_file:
        with open(args.items_file, newline="", encoding="utf-8-sig") as f:
            for row in csv.reader(f):
                row = [c.strip() for c in row if c.strip()]
                if not row:
                    continue
                try:
                    receipt.parse_price(row[1] if len(row) > 1 else "")
                except ValueError:
                    continue                     # header line ("name,price,qty") or junk
                data["items"].append(row[:3])
    for fields in args.item or []:
        if not 2 <= len(fields) <= 3:
            raise ValueError(f"--item takes NAME PRICE [QTY], got: {' '.join(fields)}")
        data["items"].append(fields)
    given = {k: getattr(args, a) for k, a in RECEIPT_FLAGS.items() if getattr(args, a, None) is not None}
    data.update(given)
    if args.number:
        data["number"] = args.number
    r = receipt.Receipt.from_dict(data)
    if given or args.json:
        config.save_extra("receipt", {k: data.get(k, "") for k in RECEIPT_HEADER})
    return r


def _products(r):
    return f"{len(r.items)} product" + ("s" if len(r.items) != 1 else "")


async def cmd_receipt(args):
    try:
        r = _receipt(args)
    except (ValueError, OSError) as e:
        sys.exit(f"Error: {e}")
    if args.preview:
        width = args.width or _offline_model(args).width
        rows, _ = api.rows_for([(r.image(width), True)], width)
        img = Image.new("1", (width, len(rows)), 1)
        img.putdata([0 if px else 1 for row in rows for px in row])
        img.save(args.preview)
        print(f"Wrote {args.preview}: {_products(r)}, total {receipt.clp(r.total)}")
        return
    print(f"Receipt N° {r.number}: {_products(r)}, total {receipt.clp(r.total)}", file=sys.stderr)
    await _print_items(args, lambda w: [(r.image(w), True)])


async def cmd_status(args):
    async with api.connect(_target(args)) as p:
        st = await api.status_async(p)
    if args.json:
        print(json.dumps(st))
    else:
        print(f"Model:   {st['model']}\nState:   {st['state'] or 'no reply'}\n"
              f"Battery: {str(st['battery']) + '%' if st['battery'] is not None else 'no reply'}")


async def cmd_feed(args):
    async with api.connect(_target(args)) as p:
        await p.send(protocol.frame(protocol.CMD_FEED, protocol.u16(args.lines), p.model.new_format))


async def cmd_preview(args):
    m = _offline_model(args)
    width = args.width or m.width
    if args.text is not None:
        items = [(imaging.text_image(args.text, width, args.size), True)]
    else:
        items = list(convert.to_images(args.file, width, args.size, _parse_pages(args.pages)))
    rows, _ = api.rows_for(items, width, dither=not args.no_dither)
    img = Image.new("1", (width, len(rows)), 1)
    img.putdata([0 if px else 1 for row in rows for px in row])
    img.save(args.out)
    print(f"Wrote {args.out}: {width}x{len(rows)} dots ({len(rows) / m.dpi * 25.4:.0f} mm of paper)")


async def cmd_forget(args):
    config.forget()
    print("Forgot the remembered printer.")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ipreent", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    def common_args(p, rle_default=None):
        g = p.add_argument_group("connection (normally automatic)")
        g.add_argument("-a", "--address", help="BLE address")
        g.add_argument("-p", "--port", help="Bluetooth serial port, e.g. COM5 or /dev/cu.SC03h-5363")
        g.add_argument("--rfcomm", metavar="MAC", help="RFCOMM socket to this MAC (Windows/Linux)")
        g.add_argument("--ble", action="store_true", help="force Bluetooth LE even for serial models")
        g.add_argument("-m", "--model", help="force a model profile, e.g. SC03h, GB01")
        g = p.add_argument_group("print tuning")
        g.add_argument("--width", type=int, help="dots per line (default from model)")
        g.add_argument("--energy", type=_energy,
                       help="heat: lightest (5000), lighter (6000), normal (8000, default), "
                            "darker (12000), darkest (17000), or a number")
        g.add_argument("--speed", type=int, help="lower = slower and darker")
        g.add_argument("--rle", action=argparse.BooleanOptionalAction, default=rle_default,
                       help="compressed lines on/off")

    common_args(ap)
    # Same options after the subcommand (`ipreent text hi --ble`); SUPPRESS keeps the
    # values given before it.
    common = argparse.ArgumentParser(add_help=False, argument_default=argparse.SUPPRESS)
    common_args(common, argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    _add = sub.add_parser
    sub.add_parser = lambda *a, **k: _add(*a, parents=[common], **k)

    def job_args(s):
        s.add_argument("-n", "--copies", type=int, default=1)
        s.add_argument("--feed", type=int, help="blank lines after the print (default ~96)")
        s.add_argument("--size", type=int, default=28, help="font size for text, in dots")

    s = sub.add_parser("scan", help="list nearby printers")
    s.add_argument("-t", "--timeout", type=float, default=6.0)
    s.set_defaults(fn=cmd_scan)

    s = sub.add_parser("print", help="print files: images, PDF, text (- = stdin)")
    s.add_argument("files", nargs="+")
    s.add_argument("--pages", help="PDF pages, e.g. 1,3-5")
    s.add_argument("--no-dither", action="store_true", help="hard black/white (line art, QR codes)")
    job_args(s)
    s.set_defaults(fn=cmd_print)

    s = sub.add_parser("text", help="print text from arguments or stdin")
    s.add_argument("text", nargs="*")
    job_args(s)
    s.set_defaults(fn=cmd_text)

    s = sub.add_parser(
        "receipt", help="print a receipt: business, products, total in CLP, barcode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Print a receipt with your business details, the products, their quantity and "
                    "price,\nthe total in Chilean pesos ($12.990) and a barcode with the receipt number "
                    "(the print\ntime, so no counter has to be stored or synced). Business, address, website "
                    "and footer\nare remembered for next time.",
        epilog="examples:\n"
               '  ipreent receipt -b "Industrias MT" --addr "Maipú, Santiago" --url industriasmt.cl \\\n'
               '                  -i "Empanada de pino" 2990 2 -i "Café" 1.800\n'
               "  ipreent receipt --items-file products.csv        # rows: name,price[,qty]\n"
               "  ipreent receipt --json sale.json --preview r.png  # see it without printing\n"
               '  JSON: {"business": "...", "items": [{"name": "Café", "price": 1800, "qty": 2}]}')
    s.add_argument("-i", "--item", nargs="+", action="append", metavar="FIELD",
                   help="a product: NAME PRICE [QTY] (repeat for each product)")
    s.add_argument("-b", "--business", help="business name (remembered)")
    s.add_argument("--business-address", "--addr", dest="biz_address", metavar="ADDRESS",
                   help="business address (remembered)")
    s.add_argument("--url", help="website (remembered)")
    s.add_argument("--footer", help=f'message at the bottom (default "{receipt.DEFAULT_FOOTER}")')
    s.add_argument("--items-file", metavar="CSV", help="products from a CSV file: name,price[,qty]")
    s.add_argument("--json", metavar="FILE", help="whole receipt as JSON (- = stdin)")
    s.add_argument("--number", help="receipt number for the barcode (default: date and time)")
    s.add_argument("--preview", metavar="PNG", help="save a picture instead of printing")
    s.add_argument("-n", "--copies", type=int, default=1)
    s.add_argument("--feed", type=int, help="blank lines after the print (default ~96)")
    s.set_defaults(fn=cmd_receipt)

    s = sub.add_parser("status", help="paper / battery")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("feed", help="feed blank paper")
    s.add_argument("lines", type=int, nargs="?", default=100)
    s.set_defaults(fn=cmd_feed)

    s = sub.add_parser("preview", help="save a PNG of exactly what would print (no printer needed)")
    s.add_argument("file", nargs="?")
    s.add_argument("--text")
    s.add_argument("--pages")
    s.add_argument("--size", type=int, default=28)
    s.add_argument("--no-dither", action="store_true")
    s.add_argument("-o", "--out", default="preview.png")
    s.set_defaults(fn=cmd_preview)

    s = sub.add_parser("forget", help="forget the remembered printer")
    s.set_defaults(fn=cmd_forget)

    args = ap.parse_args(argv)
    if args.cmd == "preview" and not args.file and args.text is None:
        ap.error("preview needs a file or --text")
    try:
        asyncio.run(args.fn(args))
    except api.PrinterNotFound as e:
        sys.exit(f"Error: {e}")
    except convert.Unsupported as e:
        sys.exit(f"Error: {e}")
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
