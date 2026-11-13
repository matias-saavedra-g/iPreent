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
from . import i18n
from .i18n import tr, trn


ENERGY_PRESETS = {"lightest": 5000, "lighter": 6000, "normal": 8000, "darker": 12000, "darkest": 17000}
DEFAULT_ENERGY = ENERGY_PRESETS["normal"]


def _energy(v):
    if v.lower() in ENERGY_PRESETS:
        return ENERGY_PRESETS[v.lower()]
    try:
        return int(v)
    except ValueError:
        raise argparse.ArgumentTypeError(
            tr("expected a number or one of: {0}", ', '.join(ENERGY_PRESETS))) from None


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
    print(tr("\r  sending {0:3d}%", 100 * done // total), end="" if done < total else "\n",
          file=sys.stderr, flush=True)


def _progress_eta(seconds):
    """Progress line with a countdown: the paper keeps moving after the last byte is sent."""
    t0 = time.monotonic()

    def show(done, total):
        left = protocol.format_eta(max(0.0, seconds - (time.monotonic() - t0)))
        end = "" if done < total else "\n"
        print(tr("\r  sending {0:3d}% · about {1} left ", 100 * done // total, left), end=end, file=sys.stderr, flush=True)
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
        msg = tr("The printer is busy: ") + busy.describe(info)
        start = protocol.format_eta(busy.queue_remaining(info))
        if getattr(args, "no_wait", False):
            sys.exit(msg + tr(". Not printed (--no-wait)."))
        if not getattr(args, "yes", False) and sys.stdin.isatty() and sys.stderr.isatty():
            if not _ask(tr("{0}.\nAdd this print to the queue? It should start in about {1}.", msg, start)):
                sys.exit(tr("Not printed."))
        else:
            print(tr("{0}. Queued; it should start in about {1}.", msg, start), file=sys.stderr)

        def waiting(info):
            if info:
                left = protocol.format_eta(busy.queue_remaining(info))
                print(tr("\r  waiting in the queue · about {0} ", left), end="", file=sys.stderr, flush=True)
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
        sys.exit(tr("Nothing to print."))
    lock = await _take_turn(args, label, api.estimate(len(rows), guess, args.copies, feed=args.feed,
                                                      energy=_job_energy(args)))
    try:
        async with api.connect(_target(args)) as p:
            if p.model.width != width:     # first print on a new printer: lay it out again
                rows, mode = api.rows_for(make_items(p.model.width), p.model.width, dither=dither)
            seconds = api.estimate(len(rows), p.model, args.copies, connect=False, feed=args.feed)
            lock.publish(label, seconds, APP)
            mm = protocol.paper_mm(len(rows), p.model.dpi)
            print(tr("{0}: {1} lines ({2:.0f} mm) x{3}, about {4}", p.model.name, len(rows), mm, args.copies, protocol.format_eta(seconds)), file=sys.stderr)
            await api.print_rows(p, rows, mode, args.copies, _progress_eta(seconds), feed=args.feed)
            st = await p.request(protocol.CMD_GET_STATE)
            print(tr("Printer:"), protocol.describe_state(st) if st else tr("done"), file=sys.stderr)
    finally:
        lock.release()


async def cmd_scan(args):
    found = await api.discover(args.timeout)
    if not found:
        print(tr("No printers found. Is it on, and disconnected from the phone app?"))
    for name, addr, m in found:
        link = tr("Bluetooth serial (pair it first)") if m.use_spp else "Bluetooth LE"
        print(tr("{0}  {1:<20} model={2:<10} {3} dots  {4}", addr, name, m.name, m.width, link))


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
    names = [tr("stdin") if f == "-" else f.replace("\\", "/").rsplit("/", 1)[-1] for f in args.files]
    await _print_items(args, items, names[0] + (f" +{len(names) - 1}" if len(names) > 1 else ""))


async def cmd_text(args):
    text = " ".join(args.text) if args.text else sys.stdin.read()
    first = next((l.strip() for l in text.splitlines() if l.strip()), tr("text"))
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
            raise ValueError(tr("--item takes NAME PRICE [QTY], got: {0}", " ".join(fields)))
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
    return trn("{0} product", "{0} products", len(r.items), len(r.items))


async def cmd_receipt(args):
    try:
        r = _receipt(args)
    except (ValueError, OSError) as e:
        sys.exit(tr("Error: {0}", e))
    if args.preview:
        width = args.width or _offline_model(args).width
        rows, _ = api.rows_for([(r.image(width), True)], width)
        img = Image.new("1", (width, len(rows)), 1)
        img.putdata([0 if px else 1 for row in rows for px in row])
        img.save(args.preview)
        print(tr("Wrote {0}: {1}, total {2}", args.preview, _products(r), receipt.clp(r.total)))
        return
    print(tr("Receipt N° {0}: {1}, total {2}", r.number, _products(r), receipt.clp(r.total)), file=sys.stderr)
    await _print_items(args, lambda w: [(r.image(w), True)], tr("Receipt {0}", receipt.clp(r.total)))


def _template_values(t, args):
    """Field values from the positional texts (in field order) and --set KEY=TEXT. "\\n" = new line, - = stdin."""
    values = {}
    keys = [f.key for f in t.fields]
    if len(args.text) > len(keys):
        raise templates.TemplateError(
            trn("{0} has {1} text box ({2}), got {3} texts", "{0} has {1} text boxes ({2}), got {3} texts",
                len(keys), t.name, len(keys), ", ".join(keys) or tr("none"), len(args.text)))
    values.update(zip(keys, args.text))
    for item in args.set or ():
        key, eq, text = item.partition("=")
        if not eq or key not in keys:
            raise templates.TemplateError(tr("--set needs KEY=TEXT with KEY one of: {0}", ", ".join(keys) or tr("none")))
        values[key] = text
    for k, v in values.items():
        values[k] = sys.stdin.read().rstrip("\n") if v == "-" else v.replace("\\n", "\n")
    return values


def _template_list(category=None):
    items = templates.all_templates()
    print(tr("Templates (print one with: ipreent template NAME \"your text\"; see its boxes with --fields)\n"))
    wid = max([18, *(len(t.id) for t in items)])
    wname = max([18, *(len(t.name) for t in items)])
    for cat in templates.CATEGORIES:
        label = templates.category_name(cat)
        group = [(n, t) for n, t in enumerate(items, 1) if t.category == cat]
        if not group or (category and category != cat):
            continue
        print(label)
        for n, t in group:
            boxes = ", ".join(f.key for f in t.fields) or tr("no text")
            print(f"  {n:>2}  {t.id:<{wid}} {t.name:<{wname}} {boxes}")
        print()
    print(tr("Your own SVG files in {0} show up under Mine (format: docs/TEMPLATES.md).", templates.user_dir()))


def _template_fields(t):
    print(f"{t.name} ({t.id}, {templates.category_name(t.category)}):")
    if not t.fields:
        print(tr("  no text boxes: prints the picture as it is"))
    for f in t.fields:
        how = tr("one line") if not f.multiline else (tr("one item per line") if f.list != tr("none") else tr("any length"))
        print(tr("  {0:<10} {1}, {2}. Example: {3!r}", f.key, f.label, how, f.default))
    if t.stretch is not None:
        print(tr("  The design grows longer when the text needs more room."))


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
        sys.exit(tr("Error: {0}", e))

    def items(width):
        return [(templates.render(t, values, width), True)]
    if args.preview:
        width = args.width or _offline_model(args).width
        rows, _ = api.rows_for(items(width), width)
        img = Image.new("1", (width, len(rows)), 1)
        img.putdata([0 if px else 1 for row in rows for px in row])
        img.save(args.preview)
        print(tr("Wrote {0}: {1}, {2}x{3} dots", args.preview, t.name, width, len(rows)))
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
        no_reply = tr("no reply")
        battery = str(st["battery"]) + "%" if st["battery"] is not None else no_reply
        print(tr("Model:   {0}\nState:   {1}\nBattery: {2}", st["model"], st["state"] or no_reply, battery))


async def cmd_feed(args):
    lock = await _take_turn(args, tr("feed paper"), protocol.CONNECT_S + 1)
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
        print(tr("Nothing is printing."))
        return
    if not args.watch:
        print(busy.describe(info) + ".")
        if info.get("waiting"):
            print(tr("Everything it has queued should be done in about {0}.", protocol.format_eta(busy.queue_remaining(info))))
        return
    while info:                            # live countdown until the printer is free
        print("\r" + busy.describe(info) + "   ", end="", flush=True)
        await asyncio.sleep(0.5)
        info = busy.current()
    print(tr("\nThe printer is free."))


def _speed_line():
    v = api.debug_speed()
    how = (tr("debug value; back to the nominal speed with: ipreent settings paper-speed reset") if v else
           tr("the slowest nominal speed, at every darkness"))
    return tr("paper-speed  {0:.1f} mm/s for time estimates ({1})", api.known_speed(), how)


def _settings_lines():
    e = _default_energy()
    return [tr("darkness     {0}   (lightest, lighter, normal, darker, darkest or a number)", _darkness_name(e)),
            _speed_line(), _language_line()]


def _language_line():
    """The language: the system's unless a debug choice was made (ipreent settings language)."""
    return tr("language     {0}   (system, en or es; system = follow the language of the computer)", i18n.describe())


async def cmd_settings(args):
    s = dict(_settings())
    if args.key is None:
        print(tr("Settings (change with: ipreent settings NAME VALUE)"))
        for line in _settings_lines():
            print("  " + line)
        cfg = config.load()
        print(tr("  printer      {0}", cfg.get("name") or tr("none yet (found on the first print)"))
              + (tr("   (ipreent forget / ipreent scan)") if cfg.get("name") else ""))
        if cfg.get("name"):
            m = lookup(cfg.get("model") or cfg["name"])
            how = cfg.get("port") or ("Bluetooth LE" if cfg.get("transport") == "ble" else tr("Bluetooth serial"))
            print(tr("\nPrinter details ({0} profile, {1})", m.name, how))
            for label, value in details(m):
                print(f"  {label:<13}{value}")
        return
    if args.value is None:
        sys.exit(tr("ipreent settings {0} needs a value", args.key))
    if args.key == "language":
        try:
            i18n.set_choice(args.value.lower())
        except ValueError as e:
            sys.exit(tr("Error: {0}", e))
        print(tr("Language is now {0}.", i18n.describe()))
    elif args.key == "darkness":
        try:
            s["energy"] = _energy(args.value)
        except argparse.ArgumentTypeError as e:
            sys.exit(tr("Error: {0}", e))
        config.save_extra("settings", s)
        print(tr("Darkness is now {0} (energy {1}). --energy still overrides it.", _darkness_name(s['energy']), s['energy']))
    else:                                  # paper-speed (debug: estimates assume the slowest speed)
        if args.value.lower() in ("reset", "nominal"):
            api.set_debug_speed(None)
            print(tr("Paper speed back to the nominal {0:g} mm/s (the slowest) for time estimates.", protocol.NOMINAL_MM_PER_S))
            return
        try:
            v = float(args.value)
            assert protocol.MIN_MM_PER_S <= v <= protocol.MAX_MM_PER_S
        except (ValueError, AssertionError):
            sys.exit(tr("Error: paper-speed is mm/s between {0:.0f} and {1:.0f}, or 'reset'", protocol.MIN_MM_PER_S, protocol.MAX_MM_PER_S))
        api.set_debug_speed(v)
        print(tr(("Debug: time estimates now assume {0:g} mm/s at every darkness (nominal: {1:g}; "
                   "undo with: ipreent settings paper-speed reset)."), v, protocol.NOMINAL_MM_PER_S))


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
        sys.exit(tr("Error: {0}", e))


async def cmd_bench(args):
    energies = _darkness_list(args.darkness)
    guess = _offline_model(args)
    if not energies or args.mm < 20:
        sys.exit(tr("Error: give at least one darkness level and --mm 20 or more (shorter strips are "
                 "mostly start/stop time)"))
    plan = [_bench_rows(guess.width, guess.dpi, args.mm, args.black / 100, "x") for _ in energies]
    total = sum(api.estimate(len(r), guess, feed=0, connect=False, energy=e) for r, e in zip(plan, energies))
    paper = sum(protocol.paper_mm(len(r), guess.dpi) for r in plan) + protocol.paper_mm(
        protocol.default_feed(guess.dpi), guess.dpi)
    print(tr("Bench: {0} strips of {1:g} mm at {2:g}% black, about {3:.0f} cm of paper.", len(energies), args.mm, args.black, paper / 10), file=sys.stderr)
    lock = await _take_turn(args, tr("speed bench"), protocol.CONNECT_S + total)
    results = []
    try:
        async with api.connect(_target(args, energies[0])) as p:
            m = p.model
            for e in energies:                     # no blank feed between strips: it isn't printing
                rows = _bench_rows(m.width, m.dpi, args.mm, args.black / 100,
                                   tr("iPreent bench · {0} ({1}) · {2:g}% black", _darkness_name(e), e, args.black))
                t0 = time.monotonic()
                await api.print_rows(p, rows, protocol.MODE_IMAGE, energy=e, feed=0, poll=0.1)
                secs = time.monotonic() - t0
                mm = protocol.paper_mm(len(rows), m.dpi)
                v = protocol.measured_speed(len(rows), m.dpi, 1, secs, 0)
                results.append((e, mm, secs, v, getattr(p, "busy_seen", None)))
                print(f"  {_darkness_name(e):>8} ({e:>5})  {mm:5.1f} mm  {secs:5.1f} s  "
                      + (f"{v:5.1f} mm/s" if v else tr("  too short"))
                      + ("" if getattr(p, "busy_seen", True) else
                         tr("   (the printer never said 'printing': this time may end before the paper stops)")),
                      file=sys.stderr)
            # Tear-off feed once at the end, untimed.
            await p.send(protocol.frame(protocol.CMD_FEED, protocol.u16(protocol.default_feed(m.dpi)),
                                        m.new_format))
    finally:
        lock.release()
    timed = [(e, mm / v) for e, mm, _, v, _ in results if v]
    if len(timed) >= 2:
        (e0, s0), (e1, s1) = min(timed), max(timed)
        print(tr(("\nSeconds per mm at {0} vs {1}: x{2:.2f} (x{3:.2f} if print time grew in "
                   "proportion to the heat, x1.00 if heat didn't matter)."), _darkness_name(e1), _darkness_name(e0), s1 / s0, e1 / e0))
    print(tr(("Estimates still use {0:g} mm/s; to use a measured speed instead: ipreent "
               "settings paper-speed MM_PER_S (debug)."), api.known_speed()))


HOME = {
    "print": ("ipreent print FILE...", tr("photos, PDFs, text files")),
    "text": ('ipreent text "Hello"', tr("a note (or pipe text in)")),
    "receipt": ('ipreent receipt -i "Coffee" 1800', tr("a receipt with total and barcode")),
    "template": ('ipreent template', tr("cute designs: hearts, frames, lists, tags")),
    "status": ("ipreent status", tr("paper and battery")),
    "preview": ("ipreent preview FILE", tr("PNG of what would print")),
    "queue": ("ipreent queue", tr("what is printing, time left")),
    "scan": ("ipreent scan", tr("find printers")),
    "feed": ("ipreent feed", tr("feed blank paper")),
    "settings": ("ipreent settings", tr("darkness and other defaults")),
    "bench": ("ipreent bench", tr("time a few short strips to measure the speed")),
    "forget": ("ipreent forget", tr("forget the remembered printer")),
}


def home():
    """What plain `ipreent` shows: printer, queue, settings, and the commands most likely wanted."""
    cfg = config.load()
    info = busy.current()
    print(tr("iPreent {0}: offline driver for Bluetooth thermal mini printers\n", __version__))
    if cfg.get("name"):
        how = cfg.get("port") or ("Bluetooth LE" if cfg.get("transport") == "ble" else "Bluetooth")
        printer = f"{cfg['name']} ({how})"
    else:
        printer = tr("none yet; found on the first print (or: ipreent scan)")
    print(tr("  Printer   {0}", printer))
    print(tr("  Settings  darkness {0}, estimates at {1:g} mm/s   (change: ipreent settings)", _darkness_name(_default_energy()), api.known_speed()))
    print(tr("  Queue     {0}\n", busy.describe(info) if info else tr("nothing printing")))
    order = features.ranked(features.CLI, config.load_extra("usage"))
    print(tr("Most used"))
    for key in order[:3]:
        cmd, what = HOME[key]
        print(f"  {cmd:<36}{what}")
    print(tr("\nMore: ") + ", ".join(order[3:]) + "   ·   ipreent COMMAND --help")


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
    print(tr("Wrote {0}: {1}x{2} dots ({3:.0f} mm of paper)", args.out, width, len(rows), len(rows) / m.dpi * 25.4))


async def cmd_forget(args):
    config.forget()
    print(tr("Forgot the remembered printer."))


def main(argv=None):
    argparse._ = tr          # argparse's own texts ("usage:", "error:", ...) follow the language too
    ap = argparse.ArgumentParser(prog="ipreent", description=tr(__doc__),
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    def common_args(p, rle_default=None):
        g = p.add_argument_group(tr("connection (normally automatic)"))
        g.add_argument("-a", "--address", help=tr("BLE address"))
        g.add_argument("-p", "--port", help=tr("Bluetooth serial port, e.g. COM5 or /dev/cu.SC03h-5363"))
        g.add_argument("--rfcomm", metavar="MAC", help=tr("RFCOMM socket to this MAC (Windows/Linux)"))
        g.add_argument("--ble", action="store_true", help=tr("force Bluetooth LE even for serial models"))
        g.add_argument("-m", "--model", help=tr("force a model profile, e.g. SC03h, GB01"))
        g = p.add_argument_group(tr("print tuning"))
        g.add_argument("--width", type=int, help=tr("dots per line (default from model)"))
        g.add_argument("--energy", type=_energy,
                       help=tr("heat: lightest (5000), lighter (6000), normal (8000), "
                            "darker (12000), darkest (17000), or a number; default: ipreent settings"))
        g.add_argument("--speed", type=int,
                       help=tr("the printer's speed setting (model default, SC03h: 10); higher = slower"))
        g.add_argument("--rle", action=argparse.BooleanOptionalAction, default=rle_default,
                       help=tr("compressed lines on/off"))

    common_args(ap)
    # Same options after the subcommand (`ipreent text hi --ble`); SUPPRESS keeps the
    # values given before it.
    common = argparse.ArgumentParser(add_help=False, argument_default=argparse.SUPPRESS)
    common_args(common, argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", metavar="COMMAND")
    _add = sub.add_parser
    sub.add_parser = lambda *a, **k: _add(*a, parents=[common], **k)

    def queue_args(s):
        g = s.add_argument_group(tr("when the printer is busy"))
        g.add_argument("-y", "--yes", action="store_true", help=tr("queue without asking"))
        g.add_argument("--no-wait", action="store_true", help=tr("give up instead of queueing"))

    def job_args(s):
        s.add_argument("-n", "--copies", type=int, default=1)
        s.add_argument("--feed", type=int, help=tr("blank lines after the print (default ~96)"))
        s.add_argument("--size", type=int, default=28, help=tr("font size for text, in dots"))
        queue_args(s)

    s = sub.add_parser("scan", help=tr("list nearby printers"))
    s.add_argument("-t", "--timeout", type=float, default=6.0)
    s.set_defaults(fn=cmd_scan)

    s = sub.add_parser("print", help=tr("print files: images, PDF, text (- = stdin)"))
    s.add_argument("files", nargs="+")
    s.add_argument("--pages", help=tr("PDF pages, e.g. 1,3-5"))
    s.add_argument("--no-dither", action="store_true", help=tr("hard black/white (line art, QR codes)"))
    job_args(s)
    s.set_defaults(fn=cmd_print)

    s = sub.add_parser("text", help=tr("print text from arguments or stdin"))
    s.add_argument("text", nargs="*")
    job_args(s)
    s.set_defaults(fn=cmd_text)

    s = sub.add_parser(
        "receipt", help=tr("print a receipt: business, products, total in CLP, barcode"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=tr("Print a receipt with your business details, the products, their quantity and "
                    "price,\nthe total in Chilean pesos ($12.990) and a barcode with the receipt number "
                    "(the print\ntime, so no counter has to be stored or synced). Business, address, website "
                    "and footer\nare remembered for next time."),
        epilog=tr("examples:\n"
               '  ipreent receipt -b "Industrias MT" --addr "Maipú, Santiago" --url industriasmt.cl \\\n'
               '                  -i "Empanada de pino" 2990 2 -i "Café" 1.800\n'
               "  ipreent receipt --items-file products.csv        # rows: name,price[,qty]\n"
               "  ipreent receipt --json sale.json --preview r.png  # see it without printing\n"
               '  JSON: {"business": "...", "items": [{"name": "Café", "price": 1800, "qty": 2}]}'))
    s.add_argument("-i", "--item", nargs="+", action="append", metavar="FIELD",
                   help=tr("a product: NAME PRICE [QTY] (repeat for each product)"))
    s.add_argument("-b", "--business", help=tr("business name (remembered)"))
    s.add_argument("--business-address", "--addr", dest="biz_address", metavar="ADDRESS",
                   help=tr("business address (remembered)"))
    s.add_argument("--url", help=tr("website (remembered)"))
    s.add_argument("--footer", help=tr("message at the bottom (default \"{0}\")", receipt.DEFAULT_FOOTER))
    s.add_argument("--items-file", metavar="CSV", help=tr("products from a CSV file: name,price[,qty]"))
    s.add_argument("--json", metavar="FILE", help=tr("whole receipt as JSON (- = stdin)"))
    s.add_argument("--number", help=tr("receipt number for the barcode (default: date and time)"))
    s.add_argument("--preview", metavar="PNG", help=tr("save a picture instead of printing"))
    s.add_argument("-n", "--copies", type=int, default=1)
    s.add_argument("--feed", type=int, help=tr("blank lines after the print (default ~96)"))
    queue_args(s)
    s.set_defaults(fn=cmd_receipt)

    s = sub.add_parser(
        "template", help=tr("cute designs to fill in: hearts, frames, lists, notes, tags"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=tr("Print a ready-made design (a heart, a frame, a to-do list, a gift tag…) with your own "
                    "text.\nThe text shrinks to fit; lists and frames grow longer when they need to. Without "
                    "NAME, lists\nthe templates. Your own SVG files work too (see docs/TEMPLATES.md)."),
        epilog=tr("examples:\n"
               "  ipreent template                                  # the collection\n"
               "  ipreent template big-heart \"Te quiero mucho\"\n"
               "  ipreent template birthday --set name=Yuliana --preview cake.png\n"
               "  ipreent template to-do \"Hoy\" \"Leche\\nPan\\nCafé\"         # \\n = new line\n"
               "  ipreent template gift-tag --fields                 # what you can fill in\n"
               "  ipreent template ./my-design.svg"))
    s.add_argument("name", nargs="?", help=tr("template name or number from the list, or an SVG file"))
    s.add_argument("text", nargs="*", help=tr("text for the boxes, in order (- = stdin)"))
    s.add_argument("-s", "--set", action="append", metavar="KEY=TEXT", help=tr("text for one box by name (repeatable)"))
    s.add_argument("--fields", action="store_true", help=tr("show the template's text boxes and stop"))
    s.add_argument("--category", choices=list(templates.CATEGORIES), help=tr("list only this category"))
    s.add_argument("--preview", metavar="PNG", help=tr("save a picture instead of printing"))
    s.add_argument("-n", "--copies", type=int, default=1)
    s.add_argument("--feed", type=int, help=tr("blank lines after the print (default ~96)"))
    queue_args(s)
    s.set_defaults(fn=cmd_template)

    s = sub.add_parser("status", help=tr("paper / battery"))
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("feed", help=tr("feed blank paper"))
    s.add_argument("lines", type=int, nargs="?", default=100)
    queue_args(s)
    s.set_defaults(fn=cmd_feed)

    s = sub.add_parser("queue", help=tr("what is printing right now and how long it has left"))
    s.add_argument("--watch", action="store_true", help=tr("live countdown until the printer is free"))
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_queue)

    s = sub.add_parser("settings", help=tr("show or change defaults: darkness, paper speed"),
                       description=tr("Defaults used when no option is given. "
                                   "Examples: ipreent settings darkness darker · ipreent settings paper-speed reset · "
                                   "ipreent settings language es"))
    s.add_argument("key", nargs="?", choices=["darkness", "paper-speed", "language"])
    s.add_argument("value", nargs="?")
    s.set_defaults(fn=cmd_settings)

    s = sub.add_parser("bench", help=tr("time short strips at a few darkness levels to measure the real speed"),
                       description=tr("Prints one short strip per darkness level (about 3-4 cm each, "
                                   "blank feed only after the last), times each and shows the measured speed "
                                   "for that level and how much darkness slows the printer. Estimates keep using "
                                   "the nominal 10 mm/s unless you set: ipreent settings paper-speed."))
    s.add_argument("--darkness", default="lightest,normal,darkest",
                   help=tr("comma-separated levels or energies, or 'all' (default: lightest,normal,darkest)"))
    s.add_argument("--mm", type=float, default=30, help=tr("length of each strip's pattern, at least 20 (default 30)"))
    s.add_argument("--black", type=float, default=50, help=tr("%% of dots black in the pattern (default 50)"))
    queue_args(s)
    s.set_defaults(fn=cmd_bench)

    s = sub.add_parser("preview", help=tr("save a PNG of exactly what would print (no printer needed)"))
    s.add_argument("file", nargs="?")
    s.add_argument("--text")
    s.add_argument("--pages")
    s.add_argument("--size", type=int, default=28)
    s.add_argument("--no-dither", action="store_true")
    s.add_argument("-o", "--out", default="preview.png")
    s.set_defaults(fn=cmd_preview)

    s = sub.add_parser("forget", help=tr("forget the remembered printer"))
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
        ap.error(tr("preview needs a file or --text"))
    try:
        asyncio.run(args.fn(args))
    except api.PrinterNotFound as e:
        sys.exit(tr("Error: {0}", e))
    except convert.Unsupported as e:
        sys.exit(tr("Error: {0}", e))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
