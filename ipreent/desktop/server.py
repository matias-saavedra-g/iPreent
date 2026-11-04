"""Local HTTP API: while the app is open, other programs can print through it.

    curl -X POST localhost:8787/print -H "Content-Type: application/pdf" --data-binary @doc.pdf
    curl -X POST localhost:8787/text -d "Build passed"
    curl localhost:8787/jobs/3

Endpoints (all answer JSON):
    GET  /status              app version, printer, queue
    GET  /jobs/<id>           {"id", "label", "state": queued|printing|done|failed, "error"}
    POST /print               body = image, PDF or UTF-8 text (detected from the content)
    POST /text                body = plain text, or JSON {"text", "size"}
    POST /checklist           JSON {"title", "items": [...]}
    POST /banner              body = plain text, or JSON {"text"}
    POST /qr                  body = plain text, or JSON {"text"}
    POST /barcode             body = plain text, or JSON {"text"} (Code 128)
    POST /receipt             JSON {"business", "address", "url", "footer", "number",
                              "items": [{"name", "price", "qty"}]} (total in CLP, barcode)
    POST /feed                ?lines=100
Query options for every print: dither=atkinson|floyd|threshold, darkness=1..5, copies=N,
pages=1-2,5, trim=0|1, rotate=0|1, brightness=-50..50, contrast=50..200, wait=1 (answer when printed).

Off the local machine (bind 0.0.0.0) every request needs the token: "Authorization: Bearer <token>"
or ?token=<token>.
"""
import hmac
import io
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from PIL import Image

from .. import __version__, config, imaging, receipt

MAX_BODY = 64 * 1024 * 1024


class ApiError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


class Server:
    """host/port/token come from the app; print_items(label, make_items, opts) queues a job."""

    def __init__(self, worker, print_items, defaults):
        self.worker, self.print_items, self.defaults = worker, print_items, defaults
        self.httpd = None
        self.error = ""

    @property
    def running(self):
        return self.httpd is not None

    def start(self, host, port, token):
        self.stop()
        self.token = token
        self.local_only = host in ("127.0.0.1", "localhost", "::1")
        server = self

        class Handler(_Handler):
            api = server
        try:
            self.httpd = ThreadingHTTPServer((host, port), Handler)
        except OSError as e:
            self.httpd, self.error = None, f"port {port}: {e.strerror or e}"
            return False
        self.error = ""
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return True

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None


class _Handler(BaseHTTPRequestHandler):
    api: Server
    server_version = f"iPreent/{__version__}"

    def log_message(self, *a):
        pass

    # -- plumbing --

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle(self, method):
        try:
            url = urlparse(self.path)
            q = {k: v[-1] for k, v in parse_qs(url.query).items()}
            self._auth(q)
            parts = [p for p in url.path.split("/") if p]
            fn = getattr(self, f"{method}_{parts[0] if parts else 'root'}", None)
            if not fn:
                raise ApiError(404, f"no endpoint {method.upper()} {url.path}")
            self._send(200, fn(q, *parts[1:]))
        except ApiError as e:
            self._send(e.code, {"error": str(e)})
        except Exception as e:   # bad input in a file etc.
            self._send(400, {"error": f"{type(e).__name__}: {e}"})

    def do_GET(self):
        self._handle("get")

    def do_POST(self):
        self._handle("post")

    def _auth(self, q):
        if self.api.local_only:
            return
        given = self.headers.get("Authorization", "").removeprefix("Bearer ").strip() or q.get("token", "")
        if not hmac.compare_digest(given.encode(), self.api.token.encode()):
            raise ApiError(401, "missing or wrong token (see the app's API settings)")

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ApiError(413, "body too large (64 MB max)")
        return self.rfile.read(n) if n else b""

    def _text_arg(self, key="text"):
        raw = self._body()
        if "json" in (self.headers.get("Content-Type") or ""):
            data = json.loads(raw or b"{}")
            return data.get(key, ""), data
        return raw.decode("utf-8", "replace"), {}

    def _opts(self, q):
        d = self.api.defaults()

        def num(key, lo, hi, default):
            v = int(q.get(key, default))
            if not lo <= v <= hi:
                raise ApiError(400, f"{key} must be {lo}..{hi}")
            return v

        def flag(key, default):
            return q[key].lower() in ("1", "true", "yes", "on") if key in q else default
        dither = q.get("dither", d["dither"])
        if dither not in imaging.DITHERS:
            raise ApiError(400, f"dither must be one of {', '.join(imaging.DITHERS)}")
        pages = None
        if q.get("pages"):
            from .app import parse_pages
            pages = parse_pages(q["pages"])
        return dict(method=dither, darkness=num("darkness", 1, 5, d["darkness"]),
                    copies=num("copies", 1, 50, 1), pages=pages, trim=flag("trim", d["trim"]),
                    rotate=flag("rotate", d["rotate"]),
                    brightness=num("brightness", -50, 50, d["brightness"]) / 100,
                    contrast=num("contrast", 50, 200, d["contrast"]) / 100)

    def _queue(self, q, label, make_items):
        jid = self.api.print_items(label, make_items, self._opts(q))
        if q.get("wait", "") in ("1", "true"):
            jobs = self.api.worker.jobs
            deadline = time.time() + 300
            while jobs[jid]["state"] in ("queued", "printing") and time.time() < deadline:
                time.sleep(0.2)
        return dict(self.api.worker.jobs[jid])

    # -- endpoints --

    def get_root(self, q):
        return self.get_status(q)

    def get_status(self, q):
        cfg = config.load()
        jobs = self.api.worker.jobs
        return {"app": "iPreent", "version": __version__,
                "printer": {k: cfg.get(k) for k in ("name", "model", "transport", "port")},
                "queue": [j for j in jobs.values() if j["state"] in ("queued", "printing")]}

    def get_jobs(self, q, jid=None):
        jobs = self.api.worker.jobs
        if jid is None:
            return list(jobs.values())[-50:]
        try:
            return jobs[int(jid)]
        except (KeyError, ValueError):
            raise ApiError(404, f"no job {jid}")

    def post_print(self, q):
        data = self._body()
        if not data:
            raise ApiError(400, "empty body: send an image, PDF or text")
        if data.startswith(b"%PDF"):
            kind = "pdf"
        else:
            try:
                img = Image.open(io.BytesIO(data))
                img.load()
                kind = "image"
            except Exception:
                try:
                    text = data.decode("utf-8")
                    kind = "text"
                except UnicodeDecodeError:
                    raise ApiError(415, "can't tell what this is: send an image, a PDF or UTF-8 text")
        opts = self._opts(q)
        label = q.get("name") or {"pdf": "API PDF", "image": "API picture", "text": "API text"}[kind]

        def items(width):
            from .app import pdf_images
            if kind == "pdf":
                return [(im, False) for im in pdf_images(data, width, opts["pages"], opts["trim"])]
            if kind == "image":
                return [(img, False)]
            return [(imaging.text_image(text, width), True)]
        return self._queue(q, label, items)

    def post_text(self, q):
        text, data = self._text_arg()
        if not text.strip():
            raise ApiError(400, "no text")
        size = int(data.get("size") or q.get("size") or 28)
        return self._queue(q, "API text", lambda w: [(imaging.text_image(text, w, size=size), True)])

    def post_checklist(self, q):
        raw = self._body()
        data = json.loads(raw or b"{}") if raw.strip().startswith(b"{") else \
            {"items": raw.decode("utf-8", "replace").splitlines()}
        title, items = data.get("title", ""), [str(i) for i in data.get("items", [])]
        if not items and not title:
            raise ApiError(400, 'send {"title": ..., "items": [...]}')
        return self._queue(q, "API checklist", lambda w: [(imaging.checklist_image(title, items, w), True)])

    def post_banner(self, q):
        text, _ = self._text_arg()
        if not text.strip():
            raise ApiError(400, "no text")
        return self._queue(q, "API banner", lambda w: [(imaging.banner_image(text.strip(), w), True)])

    def post_qr(self, q):
        text, _ = self._text_arg()
        if not text.strip():
            raise ApiError(400, "no text")
        return self._queue(q, "API QR code", lambda w: [(imaging.qr_image(text.strip(), w), True)])

    def post_barcode(self, q):
        text, _ = self._text_arg()
        try:
            imaging.code128(text.strip())
        except ValueError as e:
            raise ApiError(400, str(e))
        return self._queue(q, "API barcode", lambda w: [(imaging.barcode_image(text.strip(), w), True)])

    def post_receipt(self, q):
        try:
            data = json.loads(self._body() or b"{}")
            if not isinstance(data, dict):
                raise ValueError("send a JSON object")
            r = receipt.Receipt.from_dict(data)
        except ValueError as e:      # also bad JSON
            raise ApiError(400, f'{e} (send {{"business": ..., "items": [{{"name", "price", "qty"}}]}})')
        job = self._queue(q, f"API receipt {receipt.clp(r.total)}", lambda w: [(r.image(w), True)])
        return {**job, "number": r.number, "total": r.total}

    def post_feed(self, q):
        jid = self.api.worker.feed(int(q.get("lines", 100)))
        return dict(self.api.worker.jobs[jid])
