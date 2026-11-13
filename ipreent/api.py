"""High-level API. Everything here also works from other Python programs:

    import ipreent
    ipreent.print_text("Hello")
    ipreent.print_file("ticket.pdf")
    print(ipreent.status())
"""
import asyncio
import contextlib
import sys
import time
from dataclasses import dataclass, field

from PIL import Image

from . import ble, config, convert, imaging, protocol, spp
from .models import Model, lookup
from .i18n import tr


# Serial (useSPP) models confirmed on hardware to also print over BLE. BLE needs no pairing,
# so these default to it. Unverified SPP models keep using serial: over BLE they may connect
# and silently print nothing.
BLE_VERIFIED = {"SC03h"}


class PrinterNotFound(Exception):
    pass


@dataclass
class Target:
    """How to reach a printer. Any field may be empty; connect() fills in the rest."""
    name: str = ""
    address: str = ""      # BLE address (also the classic MAC on most of these chips)
    port: str = ""         # serial port for SPP models (COM5, /dev/cu.xxx, /dev/rfcomm0)
    rfcomm: str = ""       # MAC for a raw RFCOMM socket
    model: str = ""        # force a model profile
    ble: bool = False      # force BLE even for SPP models
    overrides: dict = field(default_factory=dict)   # width / energy / speed / rle

    def profile(self):
        m = lookup(self.model or self.name)
        for k, v in self.overrides.items():
            if v is not None:
                setattr(m, k, v)
        return m


def _log(*a):
    print(*a, file=sys.stderr)


async def discover(timeout=6.0):
    """[(name, address, Model)] of printers in range."""
    return [(adv.local_name or dev.name or "", dev.address, lookup(adv.local_name or dev.name or ""))
            for dev, adv in await ble.scan(timeout)]


def _transport(t, m, log):
    if t.port:
        return spp.SppPrinter(m, port=t.port), {"port": t.port}
    if t.ble or not m.use_spp or (m.name in BLE_VERIFIED and t.address and not t.rfcomm):
        if not t.address:
            raise PrinterNotFound(tr("no BLE address"))
        return ble.Printer(t.address, m), {"address": t.address, "transport": "ble"}
    if t.rfcomm:
        return spp.SppPrinter(m, mac=t.rfcomm), {"rfcomm": t.rfcomm}
    ports = spp.find_serial_ports(t.name)
    if ports:
        log(tr("{0} prints over Bluetooth serial: using {1}", m.name, ports[0]))
        return spp.SppPrinter(m, port=ports[0]), {"port": ports[0]}
    if t.address and ":" in t.address and hasattr(__import__("socket"), "AF_BLUETOOTH"):
        log(tr("{0} prints over Bluetooth serial: RFCOMM to {1}", m.name, t.address))
        return spp.SppPrinter(m, mac=t.address), {"rfcomm": t.address}
    raise PrinterNotFound(
        tr(("{0} needs a Bluetooth serial link. Pair it in your Bluetooth settings first "
             "(Windows then creates a COM port), or pass --port / --rfcomm."), m.name))


@contextlib.asynccontextmanager
async def connect(target=None, remember=True, log=_log):
    """Open a printer. Order: explicit target → remembered printer → scan."""
    t = target or Target()
    explicit = t.port or t.rfcomm or t.address
    saved = config.load()
    if not explicit and saved:
        t = Target(name=saved.get("name", ""), address=saved.get("address", ""),
                   port=saved.get("port", ""), rfcomm=saved.get("rfcomm", ""),
                   model=t.model or saved.get("model", ""), ble=t.ble or saved.get("transport") == "ble",
                   overrides=t.overrides)
    attempts = [t]
    if not explicit:
        attempts.append(None)   # fall back to a fresh scan
    last_err = None
    for att in attempts:
        if att is None:
            log(tr("Scanning for printers..."))
            found = await discover()
            if not found:
                break
            name, addr, _ = found[0]
            log(tr("Found {0} [{1}]", name, addr))
            att = Target(name=name, address=addr, model=t.model, ble=t.ble, overrides=t.overrides)
        elif not (att.port or att.rfcomm or att.address):
            continue
        m = att.profile()
        stack = contextlib.AsyncExitStack()
        try:
            printer, how = _transport(att, m, log)
            p = await stack.enter_async_context(printer)
        except PrinterNotFound as e:
            last_err = e
            continue
        except Exception as e:   # connection failures: try the next option
            last_err = e
            log(tr("Could not connect ({0}: {1})", type(e).__name__, e))
            continue
        if remember:
            config.forget()
            config.save(name=att.name, model=att.model or None, **how)
        async with stack:
            yield p
        return
    raise PrinterNotFound(str(last_err) if last_err else
                          tr("No printer found. Is it on and not connected to the phone app?"))


# ---- building jobs -------------------------------------------------------------------------

def rows_for(items, width, dither=True):
    """items: list of (PIL image, is_text). Returns (rows, mode)."""
    rows, all_text = [], True
    for img, is_text in items:
        all_text &= is_text
        rows += imaging.image_rows(img, width, dither=dither and not is_text, auto_rotate=not is_text)
    return rows, protocol.MODE_TEXT if all_text and items else protocol.MODE_IMAGE


async def print_rows(p, rows, mode=protocol.MODE_IMAGE, copies=1, progress=None, energy=None,
                     speed=None, feed=None, log=True, poll=0.5):
    job = protocol.print_job(rows, p.model, energy=energy, speed=speed, mode=mode, feed_after=feed)
    t0 = time.monotonic()
    busy_seen = False
    for _ in range(copies):
        await p.send(job, progress)
        await p.wait_done(interval=poll)
        busy_seen |= bool(getattr(p, "busy_seen", False))
    if log:
        used = p.model.energy if energy is None else energy
        log_print(len(rows), p.model, copies, time.monotonic() - t0, feed, energy=used,
                  black=black_fraction(rows), busy_seen=busy_seen)
    return job


# ---- print time ------------------------------------------------------------------------------
# Estimates use a fixed paper speed: the slowest nominal 10 mm/s, or the debug override
# (timing.json "debug_mm_per_s", set with `ipreent settings paper-speed` or the Windows debug
# settings). Timed prints are only logged (timing.json "log", raw figures, no content) so the speed
# can be checked later; they no longer change the estimates. Older files' learnt "speeds" are ignored.
LOG_SIZE = 100


def debug_speed():
    """The debug paper speed in mm/s, or None when estimates use the nominal speed."""
    v = config.load_extra("timing").get("debug_mm_per_s")
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return protocol.speed_for(v) if v > 0 else None


def set_debug_speed(mm_per_s=None):
    """Set (mm/s) or clear (None) the debug paper speed. Returns the speed estimates now use."""
    t = config.load_extra("timing")
    t.pop("speeds", None)
    t.pop("mm_per_s", None)
    if mm_per_s:
        t["debug_mm_per_s"] = round(protocol.speed_for(mm_per_s), 2)
    else:
        t.pop("debug_mm_per_s", None)
    config.save_extra("timing", t)
    return known_speed()


def known_speed(energy=None):
    """Paper speed in mm/s used for estimates (the same at every darkness; `energy` is ignored)."""
    return protocol.speed_for(debug_speed())


def estimate(lines, model, copies=1, connect=True, feed=None, energy=None):
    """Seconds this print should take (darkness no longer changes it; `energy` is kept for callers)."""
    return protocol.estimate_seconds(lines, model.dpi, copies, known_speed(), feed, connect)


def black_fraction(rows):
    dots = sum(len(r) for r in rows)
    return sum(sum(r) for r in rows) / dots if dots else 0.0


def timing_log():
    """The last LOG_SIZE timed prints, oldest first."""
    return list(config.load_extra("timing").get("log") or [])


def last_measured_speed():
    """mm/s the last long-enough timed print showed (for the debug settings only), or None."""
    for e in reversed(timing_log()):
        try:
            v = protocol.measured_speed(e["lines"], e["dpi"], e.get("copies", 1), e["seconds"], e.get("feed"))
        except (KeyError, TypeError):
            continue
        if v:
            return v
    return None


def log_print(lines, model, copies, seconds, feed=None, energy=None, black=None, busy_seen=None):
    """Log one timed print (connection excluded) in timing.json. Estimates don't use it."""
    energy = (model.energy if energy is None else energy) or protocol.REF_ENERGY
    t = config.load_extra("timing")
    feed = protocol.default_feed(model.dpi) if feed is None else feed
    entry = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "model": model.name, "energy": energy,
             "lines": lines, "feed": feed, "dpi": model.dpi, "copies": copies, "seconds": round(seconds, 2)}
    if black is not None:
        entry["black"] = round(black, 3)
    if busy_seen is not None:
        entry["busy_seen"] = busy_seen
    t.pop("speeds", None)
    t.pop("mm_per_s", None)
    t["prints"] = int(t.get("prints", 0) or 0) + 1
    t["log"] = (list(t.get("log") or []) + [entry])[-LOG_SIZE:]
    try:
        config.save_extra("timing", t)
    except OSError:
        pass


async def status_async(p):
    st = await p.request(protocol.CMD_GET_STATE)
    bat = await p.request(protocol.CMD_BATTERY)
    return {
        "model": p.model.name,
        "state": protocol.describe_state(st) if st else None,
        "battery": bat[0] if bat else None,
    }


# ---- sync convenience wrappers -------------------------------------------------------------

def _run(coro_fn, target):
    async def go():
        async with connect(target) as p:
            return await coro_fn(p)
    return asyncio.run(go())


def print_text(text, target=None, font_size=28, copies=1):
    def job(p):
        img = imaging.text_image(text, p.model.width, size=font_size)
        rows, mode = rows_for([(img, True)], p.model.width)
        return print_rows(p, rows, mode, copies)
    _run(job, target)


def print_image(img, target=None, dither=True, copies=1):
    def job(p):
        rows, mode = rows_for([(img, False)], p.model.width, dither)
        return print_rows(p, rows, mode, copies)
    _run(job, target)


def print_file(path, target=None, dither=True, copies=1, pages=None):
    def job(p):
        items = list(convert.to_images(path, p.model.width, pages=pages))
        rows, mode = rows_for(items, p.model.width, dither)
        return print_rows(p, rows, mode, copies)
    _run(job, target)


def status(target=None):
    return _run(status_async, target)
