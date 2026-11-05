"""One print at a time across the programs on this computer (command line and Windows app).

A Bluetooth printer takes a single connection, so a second program that tries to print while the
first one is printing just fails to connect. Instead, whoever prints holds an OS lock on
`print.lock` (the OS drops it if that program dies) and describes the job in `busy.json`. Everyone
else can then say what is printing and for how long, and wait their turn.
"""
import asyncio
import json
import os
import sys
import time

from . import config, protocol


def _dir():
    return config._path().parent


def _busy_file():
    return _dir() / "busy.json"


class Lock:
    """Non-blocking exclusive lock on print.lock. One per program; acquire before connecting."""

    def __init__(self):
        self.fh = None

    @property
    def held(self):
        return self.fh is not None

    def acquire(self):
        if self.fh:
            return True
        d = _dir()
        d.mkdir(parents=True, exist_ok=True)
        fh = open(d / "print.lock", "a+b")
        try:
            if sys.platform == "win32":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        self.fh = fh
        return True

    def release(self):
        if not self.fh:
            return
        try:
            _busy_file().unlink(missing_ok=True)
        except OSError:
            pass
        try:
            if sys.platform == "win32":
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            self.fh.close()
            self.fh = None

    def publish(self, label, seconds, app, after=0.0, waiting=0):
        """Tell other programs what we are printing: `seconds` for this job, `after` for the rest."""
        info = {"pid": os.getpid(), "app": app, "label": label, "started": time.time(),
                "seconds": round(seconds, 1), "after": round(after, 1), "waiting": waiting}
        tmp = _busy_file().with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(info), encoding="utf-8")
        for _ in range(5):              # Windows refuses while a reader has the file open
            try:
                os.replace(tmp, _busy_file())
                return info
            except PermissionError:
                time.sleep(0.05)
        tmp.unlink(missing_ok=True)
        return info

    async def wait(self, poll=0.3, on_wait=None):
        """Wait (without blocking the event loop) until we hold the lock."""
        while not self.acquire():
            if on_wait:
                on_wait(current())
            await asyncio.sleep(poll)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()


def current():
    """What another program is printing ({"label", "app", "started", "seconds", ...}), or None if free."""
    probe = Lock()
    if probe.acquire():
        probe.release()                 # nobody holds it: any busy.json is left over from a crash
        return None
    try:
        return json.loads(_busy_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):       # holder hasn't written it yet
        return {"label": "a print", "app": "another program", "started": time.time(), "seconds": 0,
                "after": 0, "waiting": 0}


def remaining(info, now=None):
    """Seconds left on the job that is printing."""
    now = time.time() if now is None else now
    return max(0.0, info.get("started", now) + info.get("seconds", 0) - now)


def queue_remaining(info, now=None):
    """Seconds until the other program has finished everything it has queued."""
    return remaining(info, now) + info.get("after", 0)


def describe(info, now=None):
    """'Windows app is printing "photo.jpg" (about 0:12 left, 2 more waiting)'."""
    left = remaining(info, now)
    extra = [f"about {protocol.format_eta(left)} left" if left else "finishing"]
    if info.get("waiting"):
        extra.append(f"{info['waiting']} more waiting")
    return f'{info.get("app", "another program")} is printing "{info.get("label", "a print")}" ({", ".join(extra)})'
