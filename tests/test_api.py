"""connect(): remembered printer first, then scan; errors inside the body are not retried."""
import asyncio

import pytest

from ipreent import api, config


class FakePrinter:
    opened = []

    def __init__(self, model, fail=False, **how):
        self.model, self.fail, self.how = model, fail, how

    async def __aenter__(self):
        if self.fail:
            raise OSError("unreachable")
        FakePrinter.opened.append(self.how)
        return self

    async def __aexit__(self, *exc):
        pass


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "_path", lambda: tmp_path / "config.json")
    FakePrinter.opened = []
    calls = {"scans": 0, "fail_ports": set()}

    def transport(t, m, log):
        how = {"port": t.port} if t.port else {"address": t.address, "transport": "ble"}
        return FakePrinter(m, fail=t.port in calls["fail_ports"], **how), how

    async def discover(timeout=6.0):
        calls["scans"] += 1
        return [("SC03h-5363", "AA:BB", None)]

    monkeypatch.setattr(api, "_transport", transport)
    monkeypatch.setattr(api, "discover", discover)
    return calls


def _use(target=None):
    async def go():
        async with api.connect(target, log=lambda *a: None) as p:
            return p
    return asyncio.run(go())


def test_scans_then_remembers(env):
    p = _use()
    assert env["scans"] == 1 and p.model.name == "SC03h"
    assert config.load()["name"] == "SC03h-5363"
    _use()
    assert env["scans"] == 1   # second run used the remembered printer


def test_stale_saved_port_falls_back_to_scan(env):
    config.save(name="SC03h-5363", port="COM9")
    env["fail_ports"].add("COM9")
    _use()
    assert env["scans"] == 1


def test_body_errors_are_not_retried(env):
    async def go():
        async with api.connect(None, log=lambda *a: None):
            raise ValueError("boom")
    with pytest.raises(ValueError):
        asyncio.run(go())
    assert len(FakePrinter.opened) == 1


def test_ble_verified_spp_model_prefers_ble():
    from ipreent import api
    m = api.lookup("SC03h")
    _, how = api._transport(api.Target(name="SC03h-5363", address="63:53:D0:9A:FE:58"), m, print)
    assert how["transport"] == "ble"
    _, how = api._transport(api.Target(name="SC03h-5363", port="COM5"), m, print)
    assert how == {"port": "COM5"}


class InstantPrinter:
    """Says "ready" the moment the data is in, like printers that never report "printing"."""
    def __init__(self):
        from ipreent.models import Model
        self.model, self.busy_seen = Model(), False

    async def send(self, data, progress=None):
        pass

    async def wait_done(self, interval=0.5):
        return b"\x00"


def test_print_rows_keeps_printing_until_the_estimate_is_up(monkeypatch):
    clock = {"t": 100.0}
    monkeypatch.setattr(api.time, "monotonic", lambda: clock["t"])

    async def sleep(s):
        clock["t"] += s
    monkeypatch.setattr(api.asyncio, "sleep", sleep)
    logged, held = [], []
    monkeypatch.setattr(api, "log_print", lambda lines, model, copies, seconds, *a, **k: logged.append(seconds))
    rows = [[0] * 384] * 304                   # 304 + 96 feed = 400 rows = 50 mm: 5 s at 10 mm/s, +1 s
    expected = api.estimate(len(rows), InstantPrinter().model, connect=False)
    asyncio.run(api.print_rows(InstantPrinter(), rows, on_hold=held.append))
    assert clock["t"] - 100.0 == pytest.approx(expected) and expected == pytest.approx(6.0)
    assert logged == [0.0]                     # the log keeps the printer's own (too short) time
    assert held[0] == pytest.approx(6.0) and held == sorted(held, reverse=True)
    clock["t"] = 100.0
    asyncio.run(api.print_rows(InstantPrinter(), rows, hold=False))     # bench: no waiting
    assert clock["t"] == 100.0
