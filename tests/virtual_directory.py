#!/usr/bin/env python
"""End-to-end checks for the built-in virtual-directory proxy.

The point of these tests is the promise itself: a deployed app is reachable at
``/<prefix>/<slug>/`` with nothing installed in between. So they do not mock a
proxy - they run the router against a *real* upstream process and assert what that
process saw, which is the only way to catch the class of bug that made this a
feature request (a path that 200s but serves the wrong thing, quietly).

    python tests/virtual_directory.py

Runs without nginx, without a database and without a deployment: the route table
is a stub. HTTP is driven through an ASGI transport against a stdlib echo server,
so those checks need nothing but FastAPI and httpx. The WebSocket bridge cannot be
exercised that way, so that one check starts a real uvicorn pair and is skipped if
uvicorn is not installed.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import settings  # noqa: E402
from app.services import app_proxy  # noqa: E402

_results: list[tuple[bool, str]] = []


def check(name: str, ok: bool) -> None:
    _results.append((ok, name))
    # flush: this suite drives live sockets, and the useful information is which
    # check it never got back from.
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}", flush=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --------------------------------------------------------------------------- #
# the upstream "deployed app": raw ASGI so it needs nothing but uvicorn
# --------------------------------------------------------------------------- #
UPSTREAM_APP = textwrap.dedent('''
    import json

    async def app(scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                msg = await receive()
                if msg["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif msg["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return

        headers = {k.decode(): v.decode() for k, v in scope["headers"]}
        path = scope["path"]
        query = scope.get("query_string", b"").decode()

        if scope["type"] == "websocket":
            await receive()  # accept must come first
            await send({"type": "websocket.accept", "subprotocol": None})
            await send({"type": "websocket.send", "text": "hello from the app"})
            while True:
                msg = await receive()
                if msg["type"] == "websocket.disconnect":
                    return
                if "text" in msg and msg["text"]:
                    await send({"type": "websocket.send", "text": "echo:" + msg["text"]})
                elif "bytes" in msg and msg["bytes"]:
                    await send({"type": "websocket.send", "bytes": b"echo:" + msg["bytes"]})

        body = b""
        while True:
            msg = await receive()
            body += msg.get("body", b"")
            if not msg.get("more_body"):
                break

        if path.endswith("/redirect"):
            await send({"type": "http.response.start", "status": 302,
                        "headers": [(b"location", b"/elsewhere")]})
            await send({"type": "http.response.body", "body": b""})
            return

        if path.endswith("/binary"):
            payload = bytes(range(256)) * 40
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"application/octet-stream"),
                                    (b"x-app-marker", b"binary")],
                        "trailers": False})
            await send({"type": "http.response.body", "body": payload})
            return

        payload = json.dumps({
            "method": scope["method"],
            "path": path,
            "query": query,
            "headers": headers,
            "body": body.decode("utf-8", "replace"),
        }).encode()
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json"),
                                (b"cache-control", b"no-store"),
                                (b"x-app-marker", b"upstream")]})
        await send({"type": "http.response.body", "body": payload})
''')

ATLAS_APP = textwrap.dedent('''
    import os
    from fastapi import FastAPI

    from app.api.routers.approutes import build_router

    PORT = int(os.environ["ATLAS_TEST_UPSTREAM_PORT"])
    ROUTES = {
        "my-app": {"slug": "my-app", "name": "My App", "path": f"app/my-app",
                   "port": PORT, "framework": "streamlit", "status": "running"},
        "stopped-app": {"slug": "stopped-app", "name": "Stopped App",
                        "path": "app/stopped-app", "port": None,
                        "framework": "streamlit", "status": "stopped"},
        # A real port that nothing listens on: the "still starting" case.
        "cold-app": {"slug": "cold-app", "name": "Cold App", "path": "app/cold-app",
                     "port": int(os.environ["ATLAS_TEST_DEAD_PORT"]),
                     "framework": "gradio", "status": "running"},
    }


    def resolve(slug):
        return ROUTES.get(slug)


    app = FastAPI()
    app.include_router(build_router("app", resolver=resolve))
''')


def build_test_app(upstream_port: int):
    """The ATLAS side, in-process, with a stubbed route table."""
    from fastapi import FastAPI

    from app.api.routers.approutes import build_router

    routes = {
        "my-app": {"slug": "my-app", "name": "My App", "path": "app/my-app",
                   "port": upstream_port, "framework": "streamlit", "status": "running"},
        "stopped-app": {"slug": "stopped-app", "name": "Stopped App",
                        "path": "app/stopped-app", "port": None,
                        "framework": "streamlit", "status": "stopped"},
        "cold-app": {"slug": "cold-app", "name": "Cold App", "path": "app/cold-app",
                     "port": dead_port(), "framework": "gradio", "status": "running"},
        # An app title is user input, and it is rendered on the platform's own
        # origin by the status pages - so it belongs in a proxy test, not a policy.
        "xss-app": {"slug": "xss-app", "name": "<script>alert(1)</script>",
                    "path": "app/xss-app", "port": None,
                    "framework": "streamlit", "status": "stopped"},
    }
    app_ = FastAPI()
    app_.include_router(build_router("app", resolver=lambda slug: routes.get(slug)))
    return app_


_DEAD_PORT = None


def dead_port() -> int:
    """A port that is free right now, so connecting to it fails."""
    global _DEAD_PORT
    if _DEAD_PORT is None:
        _DEAD_PORT = free_port()
    return _DEAD_PORT


# --------------------------------------------------------------------------- #
# HTTP behaviour, driven through the ASGI app
# --------------------------------------------------------------------------- #
def run_resolver_checks() -> None:
    """The database-backed half of routing, with the session swapped out.

    Everything above uses a stub resolver, which is also what the router falls back
    to in production if a lookup raises - so the real ``resolve()`` needs its own
    coverage: it is the code that decides whether a slug is a port, a stopped app,
    or nothing, and it is the only place the TTL cache lives.
    """
    from contextlib import contextmanager

    from app.api.routers import approutes
    from app.domain.enums import AppFramework, DeploymentStatus
    from app.domain.models import Deployment

    running = Deployment(id=1, topic_id=1, user_id=1, name="Real App", slug="real-app",
                         framework=AppFramework.STREAMLIT, entrypoint="app.py",
                         status=DeploymentStatus.RUNNING, internal_port=8611)
    stopped = Deployment(id=2, topic_id=1, user_id=1, name="Gone App", slug="gone-app",
                         framework=AppFramework.GRADIO, entrypoint="app.py",
                         status=DeploymentStatus.STOPPED, internal_port=8612)

    state = {"rows": [running, stopped], "queries": 0}

    class Result:
        def __init__(self, row):
            self._row = row

        def first(self):
            return self._row

    class Session:
        def exec(self, stmt):
            state["queries"] += 1
            return Result(next((r for r in state["rows"]
                               if r.slug == _slug_of(stmt)), None))

    def _slug_of(stmt):
        """The slug the real query filters on, read off the statement.

        Taking it from the compiled bind params (rather than rebuilding the query)
        keeps the fake honest: if ``resolve()`` ever stopped filtering by slug, the
        lookups below would start disagreeing and a check would fail.
        """
        for value in (stmt.compile().params or {}).values():
            if isinstance(value, str):
                return value
        return None

    @contextmanager
    def fake_scope():
        yield Session()

    original, original_ttl = approutes.session_scope, approutes.settings.deploy_route_ttl_seconds
    approutes.session_scope = fake_scope
    approutes.settings.deploy_route_ttl_seconds = 60.0
    try:
        approutes.invalidate()
        route = approutes.resolve("real-app")
        check("resolve() turns a running deployment into a port to forward to",
              bool(route) and route["port"] == 8611)
        check("resolve() names the app and its virtual directory",
              route["name"] == "Real App" and route["path"] == "app/real-app")
        check("resolve() reports the framework, which picks the health path",
              route["framework"] == "streamlit")

        before = state["queries"]
        for _ in range(8):
            approutes.resolve("real-app")
        check("the route cache absorbs an app shell's asset lookups",
              state["queries"] == before)

        approutes.invalidate("real-app")
        approutes.resolve("real-app")
        check("invalidate() re-reads after a deploy, so a link works immediately",
              state["queries"] == before + 1)

        gone = approutes.resolve("gone-app")
        check("a stopped app resolves to a route without a port (an honest page, "
              "not a blind 502)", bool(gone) and gone["port"] is None
              and gone["status"] == "stopped")

        before = state["queries"]
        check("an unknown slug is a miss, not an error", approutes.resolve("nope") is None)
        check("a miss is cached too, so scanners cannot hammer the database",
              approutes.resolve("nope") is None and state["queries"] == before + 1)

        # A lookup that blows up must degrade to "not routed", never a 500 on
        # every asset of every app page.
        @contextmanager
        def broken_scope():
            raise RuntimeError("database offline")
            yield  # pragma: no cover

        approutes.invalidate()
        approutes.session_scope = broken_scope
        check("a broken lookup degrades to a page instead of a 500",
              approutes.resolve("real-app") is None)
    finally:
        approutes.session_scope = original
        approutes.settings.deploy_route_ttl_seconds = original_ttl
        approutes.invalidate()


def run_http_checks(upstream_port: int) -> None:
    import httpx

    app_ = build_test_app(upstream_port)
    transport = httpx.ASGITransport(app=app_)

    async def go():
        out: dict = {}
        async with httpx.AsyncClient(transport=transport, base_url="http://portal.test",
                                     follow_redirects=False) as client:
            r = await client.get("/app/my-app/data.json", headers={
                "x-probe": "keepme", "accept-encoding": "gzip, br",
                "origin": "http://portal.test", "host": "portal.test",
            }, params={"page": "2"})
            out["echo"] = r.json() if r.status_code == 200 else {}
            out["echo_status"] = r.status_code
            out["echo_headers"] = dict(r.headers)

            r = await client.post("/app/my-app/upload", content=b"a" * 100_000,
                                  headers={"content-type": "application/octet-stream"})
            out["post"] = r.json() if r.status_code == 200 else {}

            out["redirect"] = await client.get("/app/my-app")
            out["upstream_redirect"] = await client.get("/app/my-app/redirect")
            out["binary"] = await client.get("/app/my-app/binary")

            r = await client.get("/app/nope/index.html", headers={"accept": "text/html"})
            out["unknown_html"] = (r.status_code, r.text)
            r = await client.get("/app/nope/x.js", headers={"accept": "application/json"})
            out["unknown_json"] = (r.status_code, r.text)
            r = await client.get("/app/xss-app/", headers={"accept": "text/html"})
            out["xss"] = (r.status_code, r.text)
            r = await client.get("/app/stopped-app/", headers={"accept": "text/html"})
            out["stopped"] = (r.status_code, r.text)
            r = await client.get("/app/cold-app/", headers={"accept": "text/html"})
            out["cold"] = (r.status_code, r.text)
        return out

    res = asyncio.run(go())
    echo = res["echo"]
    headers = echo.get("headers", {})

    check("a virtual directory reaches the app with its path intact",
          echo.get("path") == "/app/my-app/data.json")
    check("the query string survives the hop", echo.get("query") == "page=2")
    check("upstream response headers are passed through",
          res["echo_headers"].get("x-app-marker") == "upstream"
          and res["echo_status"] == 200)
    check("the router marks which app answered (debuggable without logs)",
          res["echo_headers"].get("x-atlas-app") == "my-app")
    check("custom client headers are forwarded", headers.get("x-probe") == "keepme")
    check("Host is preserved so a Streamlit origin check still passes",
          headers.get("host") == "portal.test")
    check("Origin is preserved for the same reason",
          headers.get("origin") == "http://portal.test")
    check("Accept-Encoding is not forwarded (bodies are re-streamed, not decoded)",
          "accept-encoding" not in headers)
    check("hop-by-hop headers do not cross the proxy",
          "connection" not in headers and "transfer-encoding" not in headers)
    check("X-Forwarded-Prefix tells the app where it is mounted",
          headers.get("x-forwarded-prefix") == "/app/my-app")
    check("X-Forwarded-Proto/Host are set for url_for()-style code",
          bool(headers.get("x-forwarded-proto")) and bool(headers.get("x-forwarded-host")))

    post = res["post"]
    check("a streamed POST body arrives complete",
          post.get("body", "").count("a") == 100_000 and post.get("method") == "POST")

    red = res["redirect"]
    check("bare /app/<slug> 307s to the trailing-slash form",
          red.status_code == 307 and red.headers.get("location") == "/app/my-app/")
    up = res["upstream_redirect"]
    check("a root-relative redirect from the app is re-prefixed (no escape to the portal)",
          up.headers.get("location") == "/app/my-app/elsewhere" and up.status_code == 302)

    check("a binary body is copied byte for byte",
          len(res["binary"].content) == 256 * 40)

    code, html = res["unknown_html"]
    check("an unknown slug answers 404 with a readable page, not an nginx error",
          code == 404 and "ATLAS" in html and "no app is published" in html.lower())
    code, raw = res["unknown_json"]
    check("an asset-style request gets JSON, not HTML",
          code == 404 and raw.strip().startswith("{"))
    xss_code, xss_html = res["xss"]
    check("a deployment's name is escaped in the page ATLAS renders for it",
          xss_code == 200 and "<script>alert(1)</script>" not in xss_html
          and "&lt;script&gt;" in xss_html)

    code, html = res["stopped"]
    check("a stopped app says it is stopped instead of pretending to be missing",
          code == 200 and "stopped" in html.lower())
    code, html = res["cold"]
    check("an app whose port is not listening yet gets a page that retries",
          code == 503 and "refresh" in html and "Starting up" in html)


# --------------------------------------------------------------------------- #
# a real uvicorn pair, for the WebSocket bridge
# --------------------------------------------------------------------------- #
def run_websocket_checks() -> None:
    try:
        import uvicorn  # noqa: F401
        from websockets.sync.client import connect  # type: ignore
    except ImportError as exc:
        print(f"  [SKIP] websocket bridge (needs uvicorn + websockets: {exc})")
        return

    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        (tmp / "upstream_app.py").write_text(UPSTREAM_APP)
        (tmp / "atlas_app.py").write_text(ATLAS_APP)
        app_port, atlas_port, dead = free_port(), free_port(), free_port()
        env = dict(os.environ, PYTHONPATH=f"{ROOT / 'backend'}:{tmp}",
                   ATLAS_TEST_UPSTREAM_PORT=str(app_port),
                   ATLAS_TEST_DEAD_PORT=str(dead))
        procs = []
        try:
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "upstream_app:app",
                 "--host", "127.0.0.1", "--port", str(app_port), "--log-level", "critical"],
                cwd=tmp, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT))
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "atlas_app:app",
                 "--host", "127.0.0.1", "--port", str(atlas_port), "--log-level", "critical"],
                cwd=tmp, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT))

            for port in (app_port, atlas_port):
                if not wait_for_port(port, 25.0):
                    raise RuntimeError(f"server on {port} never came up")

            with connect(f"ws://127.0.0.1:{atlas_port}/app/my-app/_stcore/stream") as ws:
                greeting = ws.recv(timeout=10)
                reply = None
                ws.send("ping-from-browser")
                for _ in range(3):
                    msg = ws.recv(timeout=10)
                    if isinstance(msg, str) and msg.startswith("echo:"):
                        reply = msg
                        break
                check("a WebSocket is bridged end to end (Streamlit depends on this)",
                      greeting == "hello from the app" and reply == "echo:ping-from-browser")

            with connect(f"ws://127.0.0.1:{atlas_port}/app/my-app/_stcore/stream") as ws:
                ws.recv(timeout=10)
                ws.send(b"raw-bytes")
                got = None
                for _ in range(3):
                    msg = ws.recv(timeout=10)
                    if isinstance(msg, bytes) and msg.startswith(b"echo:"):
                        got = msg
                        break
            check("binary WebSocket frames are forwarded as bytes, not re-encoded",
                  got == b"echo:raw-bytes")
        except Exception as exc:  # noqa: BLE001 - report, never crash the suite
            check(f"websocket bridge ran ({type(exc).__name__}: {exc})", False)
        finally:
            for proc in procs:
                proc.terminate()
            for proc in procs:
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill()


def wait_for_port(port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as s:
            s.settimeout(0.4)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.2)
    return False


# --------------------------------------------------------------------------- #
# pure units: path building, prefix sanitising, stored app URLs
# --------------------------------------------------------------------------- #
def run_unit_checks() -> None:
    from app.services import deployments as ds

    check("app_path builds the virtual directory for a slug",
          app_proxy.app_path("my-app") == "app/my-app")
    check("the app's base path and the proxy prefix are the same value",
          ds.base_url_path("my-app") == app_proxy.app_path("my-app"))

    original = settings.deploy_url_prefix
    try:
        # A prefix like "api" would shadow the API; it must be refused, silently
        # and centrally, rather than trusted to an operator's reading of the docs.
        settings.deploy_url_prefix = "api"
        check("a reserved prefix falls back to 'app' instead of shadowing the API",
              settings.deploy_prefix == "app")
        settings.deploy_url_prefix = "/research//"
        check("surrounding slashes in the prefix are normalised",
              settings.deploy_prefix == "research" and ds.base_url_path("x") == "research/x")
    finally:
        settings.deploy_url_prefix = original

    base = settings.public_base_url
    builtin = settings.deploy_builtin_proxy
    try:
        settings.public_base_url = ""
        settings.deploy_builtin_proxy = True
        check("with no base URL the app link is origin-relative (portable across hosts)",
              ds._public_url(8601, "my-app") == "/app/my-app/")
        settings.public_base_url = "https://atlas.example.com/"
        check("an explicit base URL produces an absolute link, slash-sane",
              ds._public_url(8601, "my-app") == "https://atlas.example.com/app/my-app/")
        settings.public_base_url = ""
        settings.deploy_builtin_proxy = False
        check("with the built-in proxy off the port is named, since nothing else routes it",
              ds._public_url(8601, "my-app") == "http://localhost:8601/app/my-app/")
    finally:
        settings.public_base_url = base
        settings.deploy_builtin_proxy = builtin

    desc = app_proxy.describe()
    check("the proxy describes itself for the portal", desc["pattern"] == "/app/<slug>/"
          and desc["enabled"] is True)


def main() -> int:
    print("unit: paths, prefixes and stored app URLs:")
    run_unit_checks()
    print("route resolution against the deployment table:")
    run_resolver_checks()
    print("http: the proxy against a real upstream:")
    _stdlib_echo(free_port(), run_http_checks)
    print("websocket: bridge through a live server:")
    run_websocket_checks()

    failed = [n for ok, n in _results if not ok]
    print(f"\n{len(_results) - len(failed)}/{len(_results)} checks passed")
    if failed:
        print("FAILED:")
        for n in failed:
            print("  -", n)
        return 1
    print("ALL VIRTUAL-DIRECTORY CHECKS PASSED")
    return 0


def _stdlib_echo(port: int, fn) -> None:
    """Answer on ``port`` like a deployed app would, then let ``fn`` test it.

    A stdlib server rather than uvicorn on purpose: the HTTP checks then depend on
    nothing beyond the framework already required to import the app, and they stay
    fast. It echoes exactly the things a proxy can get wrong.
    """
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        # An idle keep-alive connection must be able to time out, or shutdown()
        # waits on a read forever and the suite never finishes.
        timeout = 1

        def _respond(self):
            length = int(self.headers.get("content-length") or 0)
            body = self.rfile.read(length) if length else b""
            if self.path.endswith("/redirect"):
                self.send_response(302)
                self.send_header("Location", "/elsewhere")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            path, _, query = self.path.partition("?")
            if path.endswith("/binary"):
                payload = bytes(range(256)) * 40
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("x-app-marker", "binary")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            payload = json.dumps({
                "method": self.command,
                "path": path,
                "query": query,
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "body": body.decode("utf-8", "replace"),
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("x-app-marker", "upstream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = _respond

        def log_message(self, *args):  # keep the test output clean
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        fn(port)
    finally:
        httpd.shutdown()
        httpd.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
