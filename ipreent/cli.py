"""ipreent: print to iPrint-style thermal mini printers. No app, no account, no internet.

Examples:
  ipreent scan                       find printers
  ipreent print photo.jpg doc.pdf    print any image / PDF / text file
  ipreent text "Hello"               print text (or: echo hi | ipreent text)
  ipreent status                     paper, battery
The printer used last is remembered; `ipreent forget` clears it.
"""
import argparse
import asyncio
import json
import sys

from PIL import Image

from . import api, config, convert, imaging, protocol
from .models import lookup


def _target(args):
    return api.Target(
        address=args.address or "", port=args.port or "", rfcomm=args.rfcomm or "",
        model=args.model or "", ble=args.ble,
        overrides={"width": args.width, "energy": args.energy or None, "rle": args.rle,
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
    g = ap.add_argument_group("connection (normally automatic)")
    g.add_argument("-a", "--address", help="BLE address")
    g.add_argument("-p", "--port", help="Bluetooth serial port, e.g. COM5 or /dev/cu.SC03h-5363")
    g.add_argument("--rfcomm", metavar="MAC", help="RFCOMM socket to this MAC (Windows/Linux)")
    g.add_argument("--ble", action="store_true", help="force Bluetooth LE even for serial models")
    g.add_argument("-m", "--model", help="force a model profile, e.g. SC03h, GB01")
    g = ap.add_argument_group("print tuning")
    g.add_argument("--width", type=int, help="dots per line (default from model)")
    g.add_argument("--energy", type=int, help="heat: ~5000 light .. ~17500 dark")
    g.add_argument("--speed", type=int, help="lower = slower and darker")
    g.add_argument("--rle", action=argparse.BooleanOptionalAction, default=None,
                   help="compressed lines on/off")
    sub = ap.add_subparsers(dest="cmd", required=True)

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
