"""Classic Bluetooth serial (SPP/RFCOMM) transport, used by models flagged useSPP (e.g. SC03h).

Two ways in:
- serial port: pair the printer in the OS first; Windows then exposes an outgoing COM port,
  macOS a /dev/cu.<name> device, Linux /dev/rfcommN (via `rfcomm bind`).
- raw RFCOMM socket (Windows and Linux): connect straight to the MAC, channel 1.
"""
import asyncio
import socket
import threading
import time

from . import protocol
from .i18n import tr


def find_serial_ports(name_hint=""):
    """Bluetooth serial ports, best guesses first."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    ports = []
    for p in list_ports.comports():
        text = f"{p.device} {p.description} {p.hwid}".lower()
        if "bluetooth" in text or "bthenum" in text or "rfcomm" in text or (
                name_hint and name_hint.lower().split("-")[0] in text):
            ports.append(p.device)
    return ports


class _SerialLink:
    def __init__(self, port):
        import serial
        self.s = serial.Serial(port, 115200, timeout=0.2, write_timeout=10)

    def write(self, data):
        self.s.write(data)
        self.s.flush()

    def read(self):
        return self.s.read(256)

    def close(self):
        self.s.close()


class _SocketLink:
    def __init__(self, mac, channel=1):
        if not hasattr(socket, "AF_BLUETOOTH"):
            raise RuntimeError(tr("This Python has no RFCOMM sockets (macOS?). Pair it and use --port."))
        self.s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        self.s.connect((mac, channel))
        self.s.settimeout(0.2)

    def write(self, data):
        self.s.sendall(data)

    def read(self):
        try:
            return self.s.recv(256)
        except (socket.timeout, TimeoutError):
            return b""

    def close(self):
        self.s.close()


class SppPrinter:
    """Same interface as ble.Printer."""

    def __init__(self, model, port=None, mac=None, channel=1, log=print):
        self.model = model
        self.port, self.mac, self.channel = port, mac, channel
        self.log = log
        self.link = None
        self.can_send = threading.Event()
        self.can_send.set()
        self.replies = []
        self.replies_cv = threading.Condition()
        self.running = False

    async def __aenter__(self):
        def open_link():
            if self.port:
                return _SerialLink(self.port)
            return _SocketLink(self.mac, self.channel)
        self.link = await asyncio.to_thread(open_link)
        self.running = True
        threading.Thread(target=self._reader, daemon=True).start()
        return self

    async def __aexit__(self, *exc):
        self.running = False
        await asyncio.sleep(0.3)
        self.link.close()

    def _reader(self):
        buf = b""
        while self.running:
            try:
                data = self.link.read()
            except OSError:
                break
            if not data:
                continue
            buf = (buf + data)[-1024:]
            frames = protocol.parse_notification(buf)
            if frames:
                buf = b""
            for cmd, payload in frames:
                if cmd == protocol.CMD_FLOW:
                    (self.can_send.clear if payload[:1] == b"\x10" else self.can_send.set)()
                else:
                    with self.replies_cv:
                        self.replies.append((cmd, payload))
                        self.replies_cv.notify_all()

    def _send_blocking(self, data, progress):
        chunk = self.model.mtu or 180
        delay = min(self.model.interval_ms, 10) / 1000
        for i in range(0, len(data), chunk):
            self.can_send.wait(timeout=10)
            self.link.write(data[i:i + chunk])
            time.sleep(delay)
            if progress:
                progress(min(i + chunk, len(data)), len(data))

    async def send(self, data, progress=None):
        await asyncio.to_thread(self._send_blocking, data, progress)

    def _request_blocking(self, cmd, timeout):
        with self.replies_cv:
            self.replies.clear()
        self.link.write(protocol.frame(cmd, b"\x00", self.model.new_format))
        end = time.monotonic() + timeout
        with self.replies_cv:
            while time.monotonic() < end:
                for i, (got, payload) in enumerate(self.replies):
                    if got == cmd:
                        del self.replies[i]
                        return payload
                self.replies_cv.wait(end - time.monotonic())
        return None

    async def request(self, cmd, timeout=2.0):
        return await asyncio.to_thread(self._request_blocking, cmd, timeout)

    async def wait_done(self, timeout=60.0, interval=0.5):
        """Poll state until the printer stops reporting 'printing' (busy_seen: it ever did)."""
        end = time.monotonic() + timeout
        self.busy_seen = False
        while time.monotonic() < end:
            st = await self.request(protocol.CMD_GET_STATE)
            if st is None or not (st[0] & 0x80):
                return st
            self.busy_seen = True
            await asyncio.sleep(interval)
