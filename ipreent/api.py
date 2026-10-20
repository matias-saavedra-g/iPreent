"""High-level API. Everything here also works from other Python programs:

    import ipreent
    ipreent.print_text("Hello")
    ipreent.print_file("ticket.pdf")
    print(ipreent.status())
"""
import asyncio
import contextlib
import sys
from dataclasses import dataclass, field

from PIL import Image

from . import ble, config, convert, imaging, protocol, spp
from .models import Model, lookup


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
            raise PrinterNotFound("no BLE address")
        return ble.Printer(t.address, m), {"address": t.address, "transport": "ble"}
    if t.rfcomm:
        return spp.SppPrinter(m, mac=t.rfcomm), {"rfcomm": t.rfcomm}
    ports = spp.find_serial_ports(t.name)
    if ports:
        log(f"{m.name} prints over Bluetooth serial: using {ports[0]}")
        return spp.SppPrinter(m, port=ports[0]), {"port": ports[0]}
    if t.address and ":" in t.address and hasattr(__import__("socket"), "AF_BLUETOOTH"):
        log(f"{m.name} prints over Bluetooth serial: RFCOMM to {t.address}")
        return spp.SppPrinter(m, mac=t.address), {"rfcomm": t.address}
    raise PrinterNotFound(
        f"{m.name} needs a Bluetooth serial link. Pair it in your Bluetooth settings first "
        "(Windows then creates a COM port), or pass --port / --rfcomm.")


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
            log("Scanning for printers...")
            found = await discover()
            if not found:
                break
            name, addr, _ = found[0]
            log(f"Found {name} [{addr}]")
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
            log(f"Could not connect ({type(e).__name__}: {e})")
            continue
        if remember:
            config.forget()
            config.save(name=att.name, model=att.model or None, **how)
        async with stack:
            yield p
        return
    raise PrinterNotFound(str(last_err) if last_err else
                          "No printer found. Is it on and not connected to the phone app?")


# ---- building jobs -------------------------------------------------------------------------

def rows_for(items, width, dither=True):
    """items: list of (PIL image, is_text). Returns (rows, mode)."""
    rows, all_text = [], True
    for img, is_text in items:
        all_text &= is_text
        rows += imaging.image_rows(img, width, dither=dither and not is_text, auto_rotate=not is_text)
    return rows, protocol.MODE_TEXT if all_text and items else protocol.MODE_IMAGE


async def print_rows(p, rows, mode=protocol.MODE_IMAGE, copies=1, progress=None, energy=None,
                     speed=None, feed=None):
    job = protocol.print_job(rows, p.model, energy=energy, speed=speed, mode=mode, feed_after=feed)
    for _ in range(copies):
        await p.send(job, progress)
        await p.wait_done()
    return job


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
