"""ipreent: print to iPrint-style thermal mini printers. No app, no account, no internet.

Examples:
  ipreent scan                       find printers
  ipreent print photo.jpg doc.pdf    print any image / PDF / text file
  ipreent text "Hello"               print text (or: echo hi | ipreent text)
  ipreent status                     paper, battery
  ipreent receipt -b "My shop" -i "Coffee" 1800 -i "Empanada" 2990 2
  ipreent template                   cute designs to fill in: hearts, frames, lists, tags
  ipreent template big-heart "Te quiero"   print one with your text
  ipreent queue                      what is printing and how long it has left
  ipreent settings darkness darker   change the default darkness
The printer used last is remembered; `ipreent forget` clears it. Run `ipreent` alone for an overview.
"""
import argparse
import asyncio
import csv
import json
import sys
import time

from PIL import Image

from . import __version__, api, busy, config, convert, features, imaging, protocol, receipt, templates
from .models import details, lookup


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


APP = "ipreent (command line)"


def _settings():
    return config.load_extra("settings")


def _darkness_name(energy):
    return next((k for k, v in ENERGY_PRESETS.items() if v == energy), str(energy))


def _default_energy():
    try:
        return int(_settings().get("energy", DEFAULT_ENERGY))
    except (TypeError, ValueError):
        return DEFAULT_ENERGY


def _job_energy(args):
    return getattr(args, "energy", None) or _default_energy()


def _target(args, energy=None):
    return api.Target(
        address=args.address or "", port=args.port or "", rfcomm=args.rfcomm or "",
        model=args.model or "", ble=args.ble,
        overrides={"width": args.width, "energy": energy or _job_energy(args), "rle": args.rle,
                   "img_speed": args.speed, "text_speed": args.speed},
    )


def _offline_model(args):
    """Best guess at the model without connecting (for preview)."""
    return lookup(args.model or config.load().get("model") or config.load().get("name", ""))


def _progress(done, total):
    print(f"\r  sending {100 * done // total:3d}%", end="" if done < total else "\n",
          file=sys.stderr, flush=True)


def _progress_eta(seconds):
    """Progress line with a countdown: the paper keeps moving after the last byte is sent."""
    t0 = time.monotonic()

    def show(done, total):
        left = protocol.format_eta(max(0.0, seconds - (time.monotonic() - t0)))
        end = "" if done < total else "\n"
        print(f"\r  sending {100 * done // total:3d}% · about {left} left ", end=end, file=sys.stderr, flush=True)
    return show


def _ask(question):
    """Yes/no on the terminal; Enter means yes."""
    print(question + " [Y/n] ", end="", file=sys.stderr, flush=True)
    try:
        return input().strip().lower() not in ("n", "no")
    except EOFError:
        return True


async def _take_turn(args, label, seconds):
    """Hold the print lock, queueing behind any other program that is printing (asking first)."""
    lock = busy.Lock()
    while not lock.acquire():
        info = busy.current()
        if info is None:
            continue                       # it just finished
        msg = "The printer is busy: " + busy.describe(info)
        start = protocol.format_eta(busy.queue_remaining(info))
        if getattr(args, "no_wait", False):
            sys.exit(msg + ". Not printed (--no-wait).")
        if not getattr(args, "yes", False) and sys.stdin.isatty() and sys.stderr.isatty():
            if not _ask(f"{msg}.\nAdd this print to the queue? It should start in about {start}."):
                sys.exit("Not printed.")
        else:
            print(f"{msg}. Queued; it should start in about {start}.", file=sys.stderr)

        def waiting(info):
            if info:
                left = protocol.format_eta(busy.queue_remaining(info))
                print(f"\r  waiting in the queue · about {left} ", end="", file=sys.stderr, flush=True)
        await lock.wait(on_wait=waiting)
        print(file=sys.stderr)
    lock.publish(label, seconds, APP)
    return lock


def _parse_pages(spec):
    if not spec:
        return None
    pages = set()
    for part in spec.split(","):
        a, _, b = part.partition("-")
        pages.update(range(int(a), int(b or a) + 1))
    return pages


async def _print_items(args, make_items, label="print"):
    dither = not getattr(args, "no_dither", False)
    guess = _offline_model(args)
    width = args.width or guess.width
    rows, mode = api.rows_for(make_items(width), width, dither=dither)
    if not rows:
        sys.exit("Nothing to print.")
    lock = await _take_turn(args, label, api.estimate(len(rows), guess, args.copies, feed=args.feed,
                                                      energy=_job_energy(args)))
    try:
        async with api.connect(_target(args)) as p:
            if p.model.width != width:     # first print on a new printer: lay it out again
                rows, mode = api.rows_for(make_items(p.model.width), p.model.width, dither=dither)
            seconds = api.estimate(len(rows), p.model, args.copies, connect=False, feed=args.feed)
            lock.publish(label, seconds, APP)
            mm = protocol.paper_mm(len(rows), p.model.dpi)
            print(f"{p.model.name}: {len(rows)} lines ({mm:.0f} mm) x{args.copies}, "
                  f"about {protocol.format_eta(seconds)}", file=sys.stderr)
            await api.print_rows(p, rows, mode, args.copies, _progress_eta(seconds), feed=args.feed)
            st = await p.request(protocol.CMD_GET_STATE)
            print("Printer:", protocol.describe_state(st) if st else "done", file=sys.stderr)
    finally:
        lock.release()


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
    names = ["stdin" if f == "-" else f.replace("\\", "/").rsplit("/", 1)[-1] for f in args.files]
    await _print_items(args, items, names[0] + (f" +{len(names) - 1}" if len(names) > 1 else ""))


async def cmd_text(args):
    text = " ".join(args.text) if args.text else sys.stdin.read()
    first = next((l.strip() for l in text.splitlines() if l.strip()), "text")
    await _print_items(args, lambda w: [(imaging.text_image(text, w, args.size), True)], first[:40])


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
    await _print_items(args, lambda w: [(r.image(w), True)], f"Receipt {receipt.clp(r.total)}")


def _template_values(t, args):
    """Field values from the positional texts (in field order) and --set KEY=TEXT. "\\n" = new line, - = stdin."""
    values = {}
    keys = [f.key for f in t.fields]
    if len(args.text) > len(keys):
        raise templates.TemplateError(
            f"{t.name} has {len(keys)} text box{'es' if len(keys) != 1 else ''} ({', '.join(keys) or 'none'}), "
            f"got {len(args.text)} texts")
    values.update(zip(keys, args.text))
    for item in args.set or ():
        key, eq, text = item.partition("=")
        if not eq or key not in keys:
            raise templates.TemplateError(f"--set needs KEY=TEXT with KEY one of: {', '.join(keys) or 'none'}")
        values[key] = text
    for k, v in values.items():
        values[k] = sys.stdin.read().rstrip("\n") if v == "-" else v.replace("\\n", "\n")
    return values


def _template_list(category=None):
    items = templates.all_templates()
    print("Templates (print one with: ipreent template NAME \"your text\"; see its boxes with --fields)\n")
    wid = max([18, *(len(t.id) for t in items)])
    wname = max([18, *(len(t.name) for t in items)])
    for cat, label in templates.CATEGORIES.items():
        group = [(n, t) for n, t in enumerate(items, 1) if t.category == cat]
        if not group or (category and category != cat):
            continue
        print(label)
        for n, t in group:
            boxes = ", ".join(f.key for f in t.fields) or "no text"
            print(f"  {n:>2}  {t.id:<{wid}} {t.name:<{wname}} {boxes}")
        print()
    print(f"Your own SVG files in {templates.user_dir()} show up under Mine (format: docs/TEMPLATES.md).")


def _template_fields(t):
    print(f"{t.name} ({t.id}, {templates.CATEGORIES[t.category]}):")
    if not t.fields:
        print("  no text boxes: prints the picture as it is")
    for f in t.fields:
        how = "one line" if not f.multiline else ("one item per line" if f.list != "none" else "any length")
        print(f"  {f.key:<10} {f.label}, {how}. Example: {f.default!r}")
    if t.stretch is not None:
        print("  The design grows longer when the text needs more room.")


async def cmd_template(args):
    if not args.name:
        _template_list(args.category)
        return
    try:
        t = templates.find(args.name)
        if args.fields:
            _template_fields(t)
            return
        values = _template_values(t, args)
        templates.render(t, values, 8)          # checks the SVG draws before taking the printer
    except templates.TemplateError as e:
        sys.exit(f"Error: {e}")

    def items(width):
        return [(templates.render(t, values, width), True)]
    if args.preview:
        width = args.width or _offline_model(args).width
        rows, _ = api.rows_for(items(width), width)
        img = Image.new("1", (width, len(rows)), 1)
        img.putdata([0 if px else 1 for row in rows for px in row])
        img.save(args.preview)
        print(f"Wrote {args.preview}: {t.name}, {width}x{len(rows)} dots")
        return
    first = next((v for v in values.values() if v.strip()), t.name)
    await _print_items(args, items, f"{t.name}: {first.splitlines()[0][:30]}" if first != t.name else t.name)


async def cmd_status(args):
    info = busy.current()
    if info:                               # it can't take a second connection while printing
        if args.json:
            print(json.dumps({"state": "printing", "busy": info, "remaining": busy.remaining(info)}))
        else:
            print(busy.describe(info) + ".")
        return
    async with api.connect(_target(args)) as p:
        st = await api.status_async(p)
    if args.json:
        print(json.dumps(st))
    else:
        print(f"Model:   {st['model']}\nState:   {st['state'] or 'no reply'}\n"
              f"Battery: {str(st['battery']) + '%' if st['battery'] is not None else 'no reply'}")


async def cmd_feed(args):
    lock = await _take_turn(args, "feed paper", protocol.CONNECT_S + 1)
    try:
        async with api.connect(_target(args)) as p:
            await p.send(protocol.frame(protocol.CMD_FEED, protocol.u16(args.lines), p.model.new_format))
    finally:
        lock.release()


async def cmd_queue(args):
    info = busy.current()
    if args.json:
        print(json.dumps({"busy": info, "remaining": busy.remaining(info) if info else 0,
                          "queue_remaining": busy.queue_remaining(info) if info else 0}))
        return
    if not info:
        print("Nothing is printing.")
        return
    if not args.watch:
        print(busy.describe(info) + ".")
        if info.get("waiting"):
            print(f"Everything it has queued should be done in about "
                  f"{protocol.format_eta(busy.queue_remaining(info))}.")
        return
    while info:                            # live countdown until the printer is free
        print("\r" + busy.describe(info) + "   ", end="", flush=True)
        await asyncio.sleep(0.5)
        info = busy.current()
    print("\nThe printer is free.")


def _speed_line():
    v = api.debug_speed()
    how = ("debug value; back to the nominal speed with: ipreent settings paper-speed reset" if v else
           "the slowest nominal speed, at every darkness")
    return f"paper-speed  {api.known_speed():.1f} mm/s for time estimates ({how})"


def _settings_lines():
    e = _default_energy()
    return [f"darkness     {_darkness_name(e)}   (lightest, lighter, normal, darker, darkest or a number)",
            _speed_line()]


async def cmd_settings(args):
    s = dict(_settings())
    if args.key is None:
        print("Settings (change with: ipreent settings NAME VALUE)")
        for line in _settings_lines():
            print("  " + line)
        cfg = config.load()
        print(f"  printer      {cfg.get('name') or 'none yet (found on the first print)'}"
              + ("   (ipreent forget / ipreent scan)" if cfg.get("name") else ""))
        if cfg.get("name"):
            m = lookup(cfg.get("model") or cfg["name"])
            how = cfg.get("port") or ("Bluetooth LE" if cfg.get("transport") == "ble" else "Bluetooth serial")
            print(f"\nPrinter details ({m.name} profile, {how})")
            for label, value in details(m):
                print(f"  {label:<13}{value}")
        return
    if args.value is None:
        sys.exit(f"ipreent settings {args.key} needs a value")
    if args.key == "darkness":
        try:
            s["energy"] = _energy(args.value)
        except argparse.ArgumentTypeError as e:
            sys.exit(f"Error: {e}")
        config.save_extra("settings", s)
        print(f"Darkness is now {_darkness_name(s['energy'])} (energy {s['energy']}). --energy still overrides it.")
    else:                                  # paper-speed (debug: estimates assume the slowest speed)
        if args.value.lower() in ("reset", "nominal"):
            api.set_debug_speed(None)
            print(f"Paper speed back to the nominal {protocol.NOMINAL_MM_PER_S:g} mm/s (the slowest) "
                  "for time estimates.")
            return
        try:
            v = float(args.value)
            assert protocol.MIN_MM_PER_S <= v <= protocol.MAX_MM_PER_S
        except (ValueError, AssertionError):
            sys.exit(f"Error: paper-speed is mm/s between {protocol.MIN_MM_PER_S:.0f} and "
                     f"{protocol.MAX_MM_PER_S:.0f}, or 'reset'")
        api.set_debug_speed(v)
        print(f"Debug: time estimates now assume {v:g} mm/s at every darkness "
              f"(nominal: {protocol.NOMINAL_MM_PER_S:g}; undo with: ipreent settings paper-speed reset).")


# ---- bench: how fast the printer really is, per darkness, on little paper ----------------------
BAYER4 = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]


def _bench_rows(width, dpi, mm, black, label):
    """A small label, then `mm` of an even pattern with `black` (0-1) of its dots black."""
    rows, _ = api.rows_for([(imaging.text_image(label, width, size=20), True)], width)
    level = round(black * 16)
    band = int(mm * dpi / 25.4)
    return rows + [[1 if BAYER4[y % 4][x % 4] < level else 0 for x in range(width)] for y in range(band)]


def _darkness_list(spec):
    if spec.strip().lower() == "all":
        return list(ENERGY_PRESETS.values())
    try:
        return [_energy(v.strip()) for v in spec.split(",") if v.strip()]
    except argparse.ArgumentTypeError as e:
        sys.exit(f"Error: {e}")


async def cmd_bench(args):
    energies = _darkness_list(args.darkness)
    guess = _offline_model(args)
    if not energies or args.mm < 20:
        sys.exit("Error: give at least one darkness level and --mm 20 or more (shorter strips are "
                 "mostly start/stop time)")
    plan = [_bench_rows(guess.width, guess.dpi, args.mm, args.black / 100, "x") for _ in energies]
    total = sum(api.estimate(len(r), guess, feed=0, connect=False, energy=e) for r, e in zip(plan, energies))
    paper = sum(protocol.paper_mm(len(r), guess.dpi) for r in plan) + protocol.paper_mm(
        protocol.default_feed(guess.dpi), guess.dpi)
    print(f"Bench: {len(energies)} strips of {args.mm:g} mm at {args.black:g}% black, "
          f"about {paper / 10:.0f} cm of paper.", file=sys.stderr)
    lock = await _take_turn(args, "speed bench", protocol.CONNECT_S + total)
    results = []
    try:
        async with api.connect(_target(args, energies[0])) as p:
            m = p.model
            for e in energies:                     # no blank feed between strips: it isn't printing
                rows = _bench_rows(m.width, m.dpi, args.mm, args.black / 100,
                                   f"iPreent bench · {_darkness_name(e)} ({e}) · {args.black:g}% black")
                t0 = time.monotonic()
                await api.print_rows(p, rows, protocol.MODE_IMAGE, energy=e, feed=0, poll=0.1)
                secs = time.monotonic() - t0
                mm = protocol.paper_mm(len(rows), m.dpi)
                v = protocol.measured_speed(len(rows), m.dpi, 1, secs, 0)
                results.append((e, mm, secs, v, getattr(p, "busy_seen", None)))
                print(f"  {_darkness_name(e):>8} ({e:>5})  {mm:5.1f} mm  {secs:5.1f} s  "
                      f"{f'{v:5.1f} mm/s' if v else '  too short'}"
                      + ("" if getattr(p, "busy_seen", True) else
                         "   (the printer never said 'printing': this time may end before the paper stops)"),
                      file=sys.stderr)
            # Tear-off feed once at the end, untimed.
            await p.send(protocol.frame(protocol.CMD_FEED, protocol.u16(protocol.default_feed(m.dpi)),
                                        m.new_format))
    finally:
        lock.release()
    timed = [(e, mm / v) for e, mm, _, v, _ in results if v]
    if len(timed) >= 2:
        (e0, s0), (e1, s1) = min(timed), max(timed)
        print(f"\nSeconds per mm at {_darkness_name(e1)} vs {_darkness_name(e0)}: x{s1 / s0:.2f} "
              f"(x{e1 / e0:.2f} if print time grew in proportion to the heat, x1.00 if heat didn't matter).")
    print(f"Estimates still use {api.known_speed():g} mm/s; to use a measured speed instead: "
          "ipreent settings paper-speed MM_PER_S (debug).")


HOME = {
    "print": ("ipreent print FILE...", "photos, PDFs, text files"),
    "text": ('ipreent text "Hello"', "a note (or pipe text in)"),
    "receipt": ('ipreent receipt -i "Coffee" 1800', "a receipt with total and barcode"),
    "template": ('ipreent template', "cute designs: hearts, frames, lists, tags"),
    "status": ("ipreent status", "paper and battery"),
    "preview": ("ipreent preview FILE", "PNG of what would print"),
    "queue": ("ipreent queue", "what is printing, time left"),
    "scan": ("ipreent scan", "find printers"),
    "feed": ("ipreent feed", "feed blank paper"),
    "settings": ("ipreent settings", "darkness and other defaults"),
    "bench": ("ipreent bench", "time a few short strips to measure the speed"),
    "forget": ("ipreent forget", "forget the remembered printer"),
}


def home():
    """What plain `ipreent` shows: printer, queue, settings, and the commands most likely wanted."""
    cfg = config.load()
    info = busy.current()
    print(f"iPreent {__version__}: offline driver for Bluetooth thermal mini printers\n")
    if cfg.get("name"):
        how = cfg.get("port") or ("Bluetooth LE" if cfg.get("transport") == "ble" else "Bluetooth")
        printer = f"{cfg['name']} ({how})"
    else:
        printer = "none yet; found on the first print (or: ipreent scan)"
    print(f"  Printer   {printer}")
    print(f"  Settings  darkness {_darkness_name(_default_energy())}, "
          f"estimates at {api.known_speed():g} mm/s   (change: ipreent settings)")
    print(f"  Queue     {busy.describe(info) if info else 'nothing printing'}\n")
    order = features.ranked(features.CLI, config.load_extra("usage"))
    print("Most used")
    for key in order[:3]:
        cmd, what = HOME[key]
        print(f"  {cmd:<36}{what}")
    print("\nMore: " + ", ".join(order[3:]) + "   ·   ipreent COMMAND --help")


def _record_use(cmd):
    if cmd in features.CLI:
        try:
            config.save_extra("usage", features.record_use(config.load_extra("usage"), cmd))
        except OSError:
            pass


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
                       help="heat: lightest (5000), lighter (6000), normal (8000), "
                            "darker (12000), darkest (17000), or a number; default: ipreent settings")
        g.add_argument("--speed", type=int,
                       help="the printer's speed setting (model default, SC03h: 10); higher = slower")
        g.add_argument("--rle", action=argparse.BooleanOptionalAction, default=rle_default,
                       help="compressed lines on/off")

    common_args(ap)
    # Same options after the subcommand (`ipreent text hi --ble`); SUPPRESS keeps the
    # values given before it.
    common = argparse.ArgumentParser(add_help=False, argument_default=argparse.SUPPRESS)
    common_args(common, argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", metavar="COMMAND")
    _add = sub.add_parser
    sub.add_parser = lambda *a, **k: _add(*a, parents=[common], **k)

    def queue_args(s):
        g = s.add_argument_group("when the printer is busy")
        g.add_argument("-y", "--yes", action="store_true", help="queue without asking")
        g.add_argument("--no-wait", action="store_true", help="give up instead of queueing")

    def job_args(s):
        s.add_argument("-n", "--copies", type=int, default=1)
        s.add_argument("--feed", type=int, help="blank lines after the print (default ~96)")
        s.add_argument("--size", type=int, default=28, help="font size for text, in dots")
        queue_args(s)

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
    queue_args(s)
    s.set_defaults(fn=cmd_receipt)

    s = sub.add_parser(
        "template", help="cute designs to fill in: hearts, frames, lists, notes, tags",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Print a ready-made design (a heart, a frame, a to-do list, a gift tag…) with your own "
                    "text.\nThe text shrinks to fit; lists and frames grow longer when they need to. Without "
                    "NAME, lists\nthe templates. Your own SVG files work too (see docs/TEMPLATES.md).",
        epilog="examples:\n"
               "  ipreent template                                  # the collection\n"
               "  ipreent template big-heart \"Te quiero mucho\"\n"
               "  ipreent template birthday --set name=Yuliana --preview cake.png\n"
               "  ipreent template to-do \"Hoy\" \"Leche\\nPan\\nCafé\"         # \\n = new line\n"
               "  ipreent template gift-tag --fields                 # what you can fill in\n"
               "  ipreent template ./my-design.svg")
    s.add_argument("name", nargs="?", help="template name or number from the list, or an SVG file")
    s.add_argument("text", nargs="*", help="text for the boxes, in order (- = stdin)")
    s.add_argument("-s", "--set", action="append", metavar="KEY=TEXT", help="text for one box by name (repeatable)")
    s.add_argument("--fields", action="store_true", help="show the template's text boxes and stop")
    s.add_argument("--category", choices=list(templates.CATEGORIES), help="list only this category")
    s.add_argument("--preview", metavar="PNG", help="save a picture instead of printing")
    s.add_argument("-n", "--copies", type=int, default=1)
    s.add_argument("--feed", type=int, help="blank lines after the print (default ~96)")
    queue_args(s)
    s.set_defaults(fn=cmd_template)

    s = sub.add_parser("status", help="paper / battery")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("feed", help="feed blank paper")
    s.add_argument("lines", type=int, nargs="?", default=100)
    queue_args(s)
    s.set_defaults(fn=cmd_feed)

    s = sub.add_parser("queue", help="what is printing right now and how long it has left")
    s.add_argument("--watch", action="store_true", help="live countdown until the printer is free")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_queue)

    s = sub.add_parser("settings", help="show or change defaults: darkness, paper speed",
                       description="Defaults used when no option is given. "
                                   "Examples: ipreent settings darkness darker · ipreent settings paper-speed reset")
    s.add_argument("key", nargs="?", choices=["darkness", "paper-speed"])
    s.add_argument("value", nargs="?")
    s.set_defaults(fn=cmd_settings)

    s = sub.add_parser("bench", help="time short strips at a few darkness levels to measure the real speed",
                       description="Prints one short strip per darkness level (about 3-4 cm each, "
                                   "blank feed only after the last), times each and shows the measured speed "
                                   "for that level and how much darkness slows the printer. Estimates keep using "
                                   "the nominal 10 mm/s unless you set: ipreent settings paper-speed.")
    s.add_argument("--darkness", default="lightest,normal,darkest",
                   help="comma-separated levels or energies, or 'all' (default: lightest,normal,darkest)")
    s.add_argument("--mm", type=float, default=30, help="length of each strip's pattern, at least 20 (default 30)")
    s.add_argument("--black", type=float, default=50, help="%% of dots black in the pattern (default 50)")
    queue_args(s)
    s.set_defaults(fn=cmd_bench)

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

    # `ipreent --help` lists the commands most people want first (features.CLI weights).
    rank = {k: i for i, k in enumerate(features.ranked(features.CLI))}
    sub._choices_actions.sort(key=lambda a: rank.get(a.dest, len(rank)))

    args = ap.parse_args(argv)
    if args.cmd is None:
        home()
        return
    _record_use(args.cmd)
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
