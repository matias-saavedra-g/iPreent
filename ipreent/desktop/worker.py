"""Printer jobs run one at a time on a background asyncio thread.

Bleak's WinRT backend must not share the Qt main thread (COM apartment clash), so all Bluetooth
work happens here. Results come back to the UI through Qt signals.
"""
import asyncio
import itertools
import threading

from PySide6.QtCore import QObject, Signal

from .. import api, config, protocol


class Worker(QObject):
    queued = Signal(int, str)            # job id, label
    started = Signal(int)
    progress = Signal(int, int)          # job id, percent
    finished = Signal(int, str)          # job id, "" on success else error text
    status = Signal(dict)                # {"model", "state", "battery", "name"}
    found = Signal(list)                 # [(name, address, model name)]

    def __init__(self):
        super().__init__()
        self.loop = asyncio.new_event_loop()
        self.queue = None
        self.ids = itertools.count(1)
        self.jobs = {}                   # id -> {"label", "state", "error"} (read by the API)
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.queue = asyncio.Queue()
        self.loop.create_task(self._consume())
        self.loop.run_forever()

    async def _consume(self):
        while True:
            jid, fn = await self.queue.get()
            self.jobs[jid]["state"] = "printing"
            self.started.emit(jid)
            try:
                await fn(jid)
                self.jobs[jid]["state"] = "done"
                self.finished.emit(jid, "")
            except Exception as e:   # shown in the queue; the app keeps running
                self.jobs[jid].update(state="failed", error=str(e) or type(e).__name__)
                self.finished.emit(jid, self.jobs[jid]["error"])

    def submit(self, label, fn):
        jid = next(self.ids)
        self.jobs[jid] = {"id": jid, "label": label, "state": "queued", "error": None}
        self.queued.emit(jid, label)
        self.loop.call_soon_threadsafe(lambda: self.queue.put_nowait((jid, fn)))
        return jid

    @staticmethod
    def target(energy):
        return api.Target(overrides={"energy": energy})

    # ---- jobs ------------------------------------------------------------------------------

    def print_job(self, label, build, energy, copies=1, on_done=None):
        """build(width) -> (rows, mode), called once the real model width is known."""
        async def run(jid):
            async with api.connect(self.target(energy), log=lambda *a: None) as p:
                rows, mode = build(p.model.width)
                if not rows:
                    raise ValueError("nothing to print")
                await api.print_rows(p, rows, mode, copies,
                                     lambda d, t: self.progress.emit(jid, 100 * d // max(1, t)))
                await self._emit_status(p)
            if on_done:
                on_done()
        return self.submit(label, run)

    def feed(self, lines=100):
        async def run(jid):
            async with api.connect(log=lambda *a: None) as p:
                await p.send(protocol.frame(protocol.CMD_FEED, protocol.u16(lines), p.model.new_format))
        return self.submit("Feed paper", run)

    def refresh(self):
        async def run(jid):
            async with api.connect(log=lambda *a: None) as p:
                await self._emit_status(p)
        return self.submit("Check printer", run)

    async def _emit_status(self, p):
        st = await api.status_async(p)
        st["name"] = config.load().get("name", "") or p.model.name
        self.status.emit(st)

    def scan(self):
        async def go():
            try:
                found = await api.discover()
            except Exception:
                found = []
            self.found.emit([(n, a, m.name) for n, a, m in found])
        asyncio.run_coroutine_threadsafe(go(), self.loop)
