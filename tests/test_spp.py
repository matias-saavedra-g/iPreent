"""Drive SppPrinter against a fake serial link that behaves like the printer."""
import asyncio

from freeprint import protocol, spp
from freeprint.models import lookup


class FakeLink:
    def __init__(self):
        self.written = bytearray()
        self.outbox = []

    def write(self, data):
        self.written += data
        if data.endswith(protocol.frame(protocol.CMD_GET_STATE)):
            self.outbox.append(protocol.frame(protocol.CMD_GET_STATE, b"\x00"))

    def read(self):
        return self.outbox.pop(0) if self.outbox else b""

    def close(self):
        pass


def test_spp_print_and_status():
    model = lookup("SC03h-5363")
    assert (model.name, model.use_spp, model.rle, model.energy, model.mtu) == ("SC03h", True, True, 5000, 180)

    async def run():
        p = spp.SppPrinter(model, port="fake")
        p.link = FakeLink()
        p.running = True
        import threading
        threading.Thread(target=p._reader, daemon=True).start()
        job = protocol.print_job([[1, 0] * 192] * 50, model)
        await p.send(job)
        st = await p.wait_done(timeout=3)
        p.running = False
        return p.link.written, job, st

    written, job, st = asyncio.run(run())
    assert bytes(written).startswith(job)
    assert protocol.describe_state(st) == "ready"
