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
