import json
import urllib.request

import pytest

from ipreent.desktop.server import Server


class FakeWorker:
    def __init__(self):
        self.jobs = {}

    def feed(self, lines):
        self.jobs[1] = {"id": 1, "label": "Feed paper", "state": "queued", "error": None}
        return 1


DEFAULTS = {"dither": "atkinson", "darkness": 3, "brightness": 0, "contrast": 100, "trim": True, "rotate": True}


@pytest.fixture
def server():
    worker, queued = FakeWorker(), []

    def print_items(label, make_items, opts):
        jid = len(worker.jobs) + 1
        worker.jobs[jid] = {"id": jid, "label": label, "state": "queued", "error": None}
        queued.append((label, make_items(384), opts))
        return jid
    s = Server(worker, print_items, lambda: DEFAULTS)
    yield s, queued
    s.stop()


def call(port, path, body=None, headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def test_local_print_text_and_options(server):
    s, queued = server
    assert s.start("127.0.0.1", 0, "tok")
    port = s.httpd.server_address[1]
    code, job = call(port, "/text?darkness=5&copies=2", b"hello")
    assert code == 200 and job["state"] == "queued"
    label, items, opts = queued[0]
    assert opts["darkness"] == 5 and opts["copies"] == 2 and items[0][1] is True
    assert call(port, "/text?darkness=9", b"x")[0] == 400
    assert call(port, f"/jobs/{job['id']}")[1]["label"] == "API text"


def test_network_mode_needs_token(server):
    s, _ = server
    assert s.start("0.0.0.0", 0, "secret")
    port = s.httpd.server_address[1]
    assert call(port, "/status")[0] == 401
    assert call(port, "/status", headers={"Authorization": "Bearer wrong"})[0] == 401
    assert call(port, "/status", headers={"Authorization": "Bearer secret"})[0] == 200
    assert call(port, "/status?token=secret")[0] == 200


def test_print_detects_image(server):
    import io
    from PIL import Image
    s, queued = server
    s.start("127.0.0.1", 0, "")
    buf = io.BytesIO()
    Image.new("L", (50, 50), 0).save(buf, "PNG")
    code, _ = call(s.httpd.server_address[1], "/print", buf.getvalue(), {"Content-Type": "image/png"})
    assert code == 200 and queued[0][1][0][1] is False


def test_receipt_endpoint(server):
    s, queued = server
    s.start("127.0.0.1", 0, "")
    port = s.httpd.server_address[1]
    body = json.dumps({"business": "MT", "items": [{"name": "Café", "price": 1800, "qty": 2}]}).encode()
    code, job = call(port, "/receipt", body, {"Content-Type": "application/json"})
    assert code == 200 and job["total"] == 3600 and len(job["number"]) == 12
    assert queued[0][0] == "API receipt $3.600" and queued[0][1][0][0].width == 384
    assert call(port, "/receipt", b'{"items": []}')[0] == 400
    assert call(port, "/receipt", b"not json")[0] == 400
