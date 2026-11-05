"""Cross-program print lock: the second program sees what the first is printing."""
import asyncio
import time

from ipreent import busy


def test_lock_is_exclusive_and_described():
    a, b = busy.Lock(), busy.Lock()
    assert busy.current() is None
    assert a.acquire()
    assert not b.acquire()
    a.publish("photo.jpg", 12.0, "Windows app", after=30.0, waiting=2)
    info = busy.current()
    assert info["label"] == "photo.jpg" and info["waiting"] == 2
    assert 11 < busy.remaining(info) <= 12
    assert 41 < busy.queue_remaining(info) <= 42
    assert busy.describe(info, now=info["started"]) == \
        'Windows app is printing "photo.jpg" (about 0:12 left, 2 more waiting)'
    a.release()
    assert busy.current() is None
    assert b.acquire()
    b.release()


def test_overdue_job_says_finishing():
    info = {"app": "ipreent", "label": "x", "started": time.time() - 60, "seconds": 5}
    assert busy.remaining(info) == 0
    assert "finishing" in busy.describe(info)


def test_wait_reports_until_free():
    a, b = busy.Lock(), busy.Lock()
    a.acquire()
    a.publish("note", 1.0, "ipreent")
    seen = []

    async def go():
        asyncio.get_running_loop().call_later(0.25, a.release)
        await b.wait(poll=0.05, on_wait=seen.append)
    asyncio.run(go())
    assert b.held and seen and seen[0]["label"] == "note"
    b.release()
