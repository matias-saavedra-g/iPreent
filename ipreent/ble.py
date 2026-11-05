"""BLE transport using bleak (Windows 10/11, Linux/BlueZ, macOS)."""
import asyncio

from bleak import BleakClient, BleakScanner

from . import protocol

SERVICES = ["0000ae00", "0000ff00", "0000ab00", "0000ae80", "49535343"]
WRITE_CHARS = ["0000ae01", "0000ff02", "0000ab01", "0000ae81", "49535343-8841"]
NOTIFY_CHARS = ["0000ae02", "0000ae04", "0000ff03", "0000ab03", "49535343-1e4d"]


def _match(uuid, prefixes):
    return any(uuid.lower().startswith(p) for p in prefixes)


async def scan(timeout=6.0):
    """Return [(device, adv)] for devices advertising a known printer service or name."""
    from .models import is_known
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    out = []
    for dev, adv in found.values():
        name = adv.local_name or dev.name or ""
        if is_known(name) or any(_match(u, SERVICES) for u in adv.service_uuids):
            out.append((dev, adv))
    return out


class Printer:
    def __init__(self, address, model, log=print):
        self.address = address
        self.model = model
        self.log = log
        self.client = None
        self.write_char = None
        self.paused = asyncio.Event()
        self.paused.set()   # set = allowed to send
        self.replies = asyncio.Queue()

    async def __aenter__(self):
        self.client = BleakClient(self.address)
        await self.client.connect()
        for svc in self.client.services:
            for ch in svc.characteristics:
                if self.write_char is None and _match(ch.uuid, WRITE_CHARS):
                    self.write_char = ch
                if _match(ch.uuid, NOTIFY_CHARS) and "notify" in ch.properties:
                    await self.client.start_notify(ch, self._on_notify)
        if self.write_char is None:
            raise RuntimeError("No known write characteristic; is this a supported printer?")
        return self

    async def __aexit__(self, *exc):
        await self.client.disconnect()

    def _on_notify(self, _char, data):
        for cmd, payload in protocol.parse_notification(bytes(data)):
            if cmd == protocol.CMD_FLOW:
                if payload[:1] == b"\x10":
                    self.paused.clear()
                else:
                    self.paused.set()
            else:
                self.replies.put_nowait((cmd, payload))

    async def send(self, data, progress=None):
        mtu = getattr(self.client, "mtu_size", 23) or 23
        chunk = max(20, min(self.model.mtu, mtu - 3))
        no_rsp = "write-without-response" in self.write_char.properties
        for i in range(0, len(data), chunk):
            await self.paused.wait()
            await self.client.write_gatt_char(self.write_char, data[i:i + chunk], response=not no_rsp)
            await asyncio.sleep(self.model.interval_ms / 1000)
            if progress:
                progress(min(i + chunk, len(data)), len(data))

    async def request(self, cmd, timeout=2.0):
        while not self.replies.empty():
            self.replies.get_nowait()
        await self.send(protocol.frame(cmd, b"\x00", self.model.new_format))
        try:
            while True:
                got, payload = await asyncio.wait_for(self.replies.get(), timeout)
                if got == cmd:
                    return payload
        except asyncio.TimeoutError:
            return None

    async def wait_done(self, timeout=60.0, interval=0.5):
        """Poll state until the printer stops reporting 'printing'.

        busy_seen says whether it ever did: if not, the data was all sent but the paper may
        still be moving, so a timing that ends here is too short.
        """
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        self.busy_seen = False
        while loop.time() < end:
            st = await self.request(protocol.CMD_GET_STATE)
            if st is None or not (st[0] & 0x80):
                return st
            self.busy_seen = True
            await asyncio.sleep(interval)
