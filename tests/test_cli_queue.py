"""CLI and the print lock: --no-wait gives up, --yes queues behind the other program, ETA shown."""
import asyncio
import threading

import pytest

from ipreent import api, busy, cli, config


class FakePrinter:
    sent = []

    def __init__(self, model):
        self.model = model

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass

    async def send(self, data, progress=None):
        FakePrinter.sent.append(len(data))
        if progress:
            progress(len(data), len(data))

    async def wait_done(self, interval=0.5):
        await asyncio.sleep(0.01)

    async def request(self, cmd):
        return b"\x00"


@pytest.fixture
def printer(monkeypatch):
    FakePrinter.sent = []
    config.save(name="SC03h-5363", address="AA:BB", transport="ble")
    monkeypatch.setattr(api, "_transport", lambda t, m, log: (FakePrinter(m), {"address": t.address}))
    return FakePrinter


def test_prints_with_estimate(printer, capsys):
    cli.main(["text", "hello"])
    err = capsys.readouterr().err
    assert printer.sent and "about 0:0" in err and "left" in err
    assert busy.current() is None                       # lock released afterwards
    assert config.load_extra("usage")["text"] == 1.0


def test_no_wait_gives_up_when_busy(printer):
    other = busy.Lock()
    other.acquire()
    other.publish("photo.jpg", 30, "Windows app")
    with pytest.raises(SystemExit) as e:
        cli.main(["text", "hello", "--no-wait"])
    assert 'Windows app is printing "photo.jpg"' in str(e.value)
    assert not printer.sent
    other.release()


def test_yes_queues_behind_the_other_program(printer, capsys):
    other = busy.Lock()
    other.acquire()
    other.publish("photo.jpg", 1, "Windows app")
    threading.Timer(0.4, other.release).start()
    cli.main(["text", "hello", "-y"])
    err = capsys.readouterr().err
    assert "Queued" in err and printer.sent


def test_status_and_queue_do_not_connect_while_busy(printer, capsys):
    other = busy.Lock()
    other.acquire()
    other.publish("ticket.pdf", 20, "Windows app", after=40, waiting=1)
    cli.main(["status"])
    cli.main(["queue"])
    out = capsys.readouterr().out
    assert out.count('printing "ticket.pdf"') == 2 and "1 more waiting" in out
    assert "should be done in about 1:0" in out
    assert not printer.sent
    other.release()
    cli.main(["queue"])
    assert "Nothing is printing" in capsys.readouterr().out


def test_settings_darkness_is_the_default(printer, capsys):
    cli.main(["settings", "darkness", "darker"])
    assert cli._default_energy() == 12000
    cli.main(["settings"])
    assert "darkness     darker" in capsys.readouterr().out
    assert api.known_speed() == 10                          # the slowest nominal speed by default
    with pytest.raises(SystemExit):
        cli.main(["settings", "paper-speed", "900"])
    cli.main(["settings", "paper-speed", "25"])
    assert api.known_speed(12000) == api.known_speed(17000) == 25   # the same at every darkness
    assert config.load_extra("timing")["debug_mm_per_s"] == 25
    cli.main(["settings", "paper-speed", "reset"])
    assert api.debug_speed() is None and api.known_speed(5000) == 10


def test_prints_are_logged_but_dont_change_the_estimate(printer):
    before = api.known_speed()
    cli.main(["text", "hello", "--energy", "darkest"])
    t = config.load_extra("timing")
    entry = t["log"][-1]
    assert entry["energy"] == 17000 and entry["lines"] > 0 and 0 <= entry["black"] <= 1
    assert "mm_per_s" not in t and "speeds" not in t
    assert api.known_speed() == before == 10


def test_old_learnt_speeds_are_ignored(printer):
    config.save_extra("timing", {"speeds": {"5000": 40.0}, "mm_per_s": 40.0})
    assert api.known_speed(5000) == 10


def test_bench_times_each_darkness(printer, capsys):
    cli.main(["bench", "--darkness", "lightest,darkest", "--mm", "20"])
    err = capsys.readouterr().err
    assert len(printer.sent) == 3 and "lightest" in err and "darkest" in err   # 2 strips + feed
    log = config.load_extra("timing")["log"]
    assert [e["energy"] for e in log] == [5000, 17000]
    assert [e["feed"] for e in log] == [0, 0]               # the tear-off feed is sent untimed
