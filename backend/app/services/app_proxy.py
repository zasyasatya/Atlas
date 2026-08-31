"""The built-in reverse proxy: deployed apps as virtual directories, no nginx.

``app.services.proxy`` generates nginx config, which is the right thing to put in
front of a production box. It is also the reason a freshly deployed app used to
be unreachable until someone installed that config — the portal happily linked to
``/app/<slug>/`` while nothing was listening for that path on the ATLAS port, and
a "copy this file into nginx once" banner was the only explanation.

This module removes that dependency: ATLAS serves ``/<prefix>/<slug>/`` itself and
forwards it to the app's internal port, so a deployed app opens the moment its
process is listening. The same-origin path also means no CORS, no extra public
port, no TLS work, and it keeps working behind any host that already reaches the
portal (a bare VM, docker, a port-addressed sandbox preview).

What is forwarded, and why:

* **The path verbatim.** Apps are launched with a matching base path
  (``--server.baseUrlPath=app/<slug>`` for Streamlit, ``GRADIO_ROOT_PATH`` for
  Gradio), so they emit and request URLs that already contain the prefix.
  Forwarding the incoming path unchanged is what the generated
  ``proxy_pass http://127.0.0.1:<port>/<prefix>/<slug>/;`` in nginx does, so the
  two layers behave identically and an app never notices which one answered.
* **The client's ``Host`` and ``Origin``.** Streamlit rejects a WebSocket whose
  ``Origin`` does not match its ``Host``; rewriting either turns a working app
  into a blank page with a 403. They are passed through untouched.
* **No ``Accept-Encoding``.** Responses are piped through as raw bytes, so the
  upstream is asked for an uncompressed body instead of guessing whether the
  client can decode it.
* **Hop-by-hop headers in both directions** (``connection``, ``keep-alive``,
  ``transfer-encoding``, ``content-length``, ``upgrade`` …) are dropped: they
  describe one TCP connection, not the end-to-end request.
* **WebSockets are bridged.** Streamlit's UI is useless without
  ``_stcore/stream``, so the bridge is not a bonus feature — it is what makes an
  app under a virtual directory behave like the app.

Every failure mode is a page the user can read, never a stack trace: an app that
is still building, one that has stopped, and a slug that does not exist each get
their own answer, and the "starting" page reloads itself so a first visit during
a slow pip install turns into a working app without touching anything.
"""
from __future__ import annotations

import asyncio
from html import escape as _esc
from typing import Any

import httpx
from fastapi import Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask
from starlette.websockets import WebSocketDisconnect

from app.core.config import settings

# Headers that describe a single hop. Forwarding them verbatim is how proxies end
# up with doubled Content-Length, a dead keep-alive or a leaked 101 handshake.
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade",
}
# ...and what the *response* must not inherit: our reply is re-framed (chunked)
# because the body is re-streamed, so the upstream's framing no longer applies.
FRAMING = {"content-length", "content-encoding"}
# Asked for, but not honoured: the body is copied byte for byte, so an encoded
# upstream response would have to be decoded and re-encoded to be correct.
DROP_REQUEST = HOP_BY_HOP | {"accept-encoding"}
# ...and the two a client library re-adds to every request on its own. httpx
# merges its defaults over anything we pass, so a proxy that only filtered the
# incoming headers would still announce "gzip" and "keep-alive" to the app -
# which is exactly the pair that makes a re-streamed body lie about itself.
PROXY_NOISE = {"accept-encoding", "connection"}
DROP_RESPONSE = HOP_BY_HOP | FRAMING

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD")

# One client per event loop, reused so an app shell that asks for 40 small files
# pays one TCP handshake instead of forty.
_clients: dict[int, httpx.AsyncClient] = {}


def prefix() -> str:
    """The single path segment apps are mounted under, e.g. ``app``."""
    return settings.deploy_prefix


def app_path(slug: str) -> str:
    """``app/<slug>`` — the virtual directory of one app (no leading slash)."""
    return f"{prefix()}/{slug}".strip("/")


def _client() -> httpx.AsyncClient:
    key = id(asyncio.get_running_loop())
    client = _clients.get(key)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            # An app booting a 2 GB model can hold a request open for minutes;
            # a read timeout would surface as a broken UI, so none is set.
            timeout=httpx.Timeout(connect=3.0, read=None, write=None, pool=10.0),
            limits=httpx.Limits(max_connections=200, max_keepalive_connections=64),
            follow_redirects=False,
        )
        _clients[key] = client
    return client


def request_headers(request: Request, route: dict | None = None) -> dict[str, str]:
    """The incoming headers, minus what must not cross a second hop."""
    out = {k: v for k, v in request.headers.items() if k.lower() not in DROP_REQUEST}
    out["x-forwarded-host"] = request.headers.get("host", "")
    out["x-forwarded-proto"] = request.url.scheme
    client_host = request.client.host if request.client else ""
    if client_host:
        existing = out.get("x-forwarded-for")
        out["x-forwarded-for"] = f"{existing}, {client_host}" if existing else client_host
    # Tells the app which URL prefix ATLAS mounted it under, the same header the
    # generated nginx config sends, so neither layer needs an app-specific tweak.
    if route:
        out["x-forwarded-prefix"] = f"/{route['path']}"
    return out


def upstream_target(route: dict, request: Request) -> str:
    """Absolute URL of the upstream request: port + path (verbatim) + query."""
    url = f"http://127.0.0.1:{route['port']}{request.url.path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"
    return url


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
async def proxy_http(request: Request, route: dict) -> Response:
    """Forward one HTTP request to the app's port and stream the reply back.

    ``route`` is ``{"slug", "name", "port", "path", ...}`` as produced by the
    router's lookup. Any upstream failure becomes a readable page (or JSON for
    XHR calls) rather than a 502 from the process manager.
    """
    headers = request_headers(request, route)
    has_body = request.method in ("POST", "PUT", "PATCH", "DELETE")
    # The body is piped, not buffered: dataset uploads are routinely hundreds of
    # megabytes and must not land in memory on the way to the app.
    content = request.stream() if has_body else None

    try:
        client = _client()
        upstream = client.build_request(
            method=request.method, url=upstream_target(route, request),
            headers=headers, content=content,
        )
        upstream.headers = httpx.Headers(
            [(k, v) for k, v in upstream.headers.multi_items()
             if k.lower() not in PROXY_NOISE]
        )
        res = await client.send(upstream, stream=True)
    except httpx.ConnectError:
        return _unreachable(request, route)
    except (httpx.HTTPError, OSError) as exc:
        return _failed(request, route, str(exc))

    forwarded = {k: v for k, v in res.headers.items() if k.lower() not in DROP_RESPONSE}
    # A redirect the app built without the prefix (a hand-written
    # ``gr.redirect("/")``, say) would drop the visitor out of the app's virtual
    # directory and onto the portal, so relative targets are re-prefixed.
    location = forwarded.get("location")
    if location and location.startswith("/") and not location.startswith(f"/{route['path']}"):
        forwarded["location"] = f"/{route['path']}{location}"

    return StreamingResponse(
        res.aiter_raw(), status_code=res.status_code, headers=forwarded,
        media_type=res.headers.get("content-type"),
        background=BackgroundTask(res.aclose),
    )


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return True
    # An app shell navigation has no Accept at all in a few embedded webviews;
    # only XHR/fetch-style requests clearly want JSON.
    return "application/json" not in accept and request.headers.get(
        "x-requested-with") != "XMLHttpRequest"


def _unreachable(request: Request, route: dict) -> Response:
    """Nothing is listening on the app's port yet."""
    detail = (f"Nothing is listening on 127.0.0.1:{route['port']} yet. The app is "
              f"most likely still starting: the first deploy installs its "
              f"dependencies, which can take a few minutes.")
    if not _wants_html(request):
        return JSONResponse({"detail": detail, "slug": route["slug"],
                             "status": "starting"}, status_code=503)
    return _notice(request, route, title="Starting up", detail=detail, retry=3)


def _failed(request: Request, route: dict, error: str) -> Response:
    # Escaped because it is a string that came back from another process, and it
    # is about to be rendered as HTML on the platform's own origin.
    detail = f"The app is listening but did not answer: {_esc(error[:400])}"
    if not _wants_html(request):
        return JSONResponse({"detail": detail, "slug": route["slug"]}, status_code=502)
    return _notice(request, route, title="App error", detail=detail, retry=6)


# --------------------------------------------------------------------------- #
# Status / not-found pages
# --------------------------------------------------------------------------- #
def _notice(request: Request, route: dict, *, title: str, detail: str,
            retry: int | None, status: int | None = None) -> HTMLResponse:
    """A small branded interstitial, styled like the platform, not like nginx."""
    refresh = f'<meta http-equiv="refresh" content="{retry}">' if retry else ""
    port = route.get("port")
    # Names come from user input (a deployment's title), so everything that is
    # interpolated into this page is escaped here rather than at each caller.
    name = _esc(str(route.get("name") or route.get("slug") or "App"))
    path = _esc(str(route.get("path") or app_path(str(route.get("slug", "")))))
    return HTMLResponse(
        f"""<!doctype html><html><head><meta charset="utf-8">
<title>{name} - {_esc(settings.app_name)}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">{refresh}
<style>
 body{{font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;background:#F6F8F6;
  color:#12160F;display:grid;place-items:center;min-height:100vh;margin:0;padding:24px}}
 .card{{max-width:560px;width:100%;background:#fff;border:1px solid #E2E8E2;
  border-radius:20px;padding:36px}}
 .mark{{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:#7C887B;
  margin-bottom:10px;font-weight:700}}
 h1{{margin:0 0 10px;font-size:22px;letter-spacing:-.02em}}
 .path{{font-family:ui-monospace,monospace;background:#EEF2EE;padding:2px 7px;
  border-radius:6px;font-size:12.5px}}
 p{{color:#3E463A;line-height:1.65;font-size:14.5px;margin:0 0 14px}}
 .spin{{width:26px;height:26px;border:3px solid #DCE6DC;border-top-color:#487058;
  border-radius:50%;animation:s 0.9s linear infinite;margin-bottom:16px}}
 @keyframes s{{to{{transform:rotate(360deg)}}}}
 a{{color:#487058;font-weight:600;text-decoration:none}}
 .foot{{margin-top:22px;padding-top:16px;border-top:1px solid #EEF2EE;
  font-size:12px;color:#7C887B}}
</style></head><body><div class="card">
<div class="mark">{_esc(settings.app_name)} &middot; {_esc(settings.app_tagline_short)}</div>
{"" if not retry else '<div class="spin"></div>'}
<h1>{_esc(title)}</h1>
<p><b>{name}</b> is served at
 <span class="path">/{path}</span></p>
<p>{detail}</p>
{f'<p>Internal port <span class="path">127.0.0.1:{port}</span>. This page reloads every {retry}s.</p>' if retry else ''}
<div class="foot"><a href="/">Back to {settings.app_name}</a></div>
</div></body></html>""",
        # 503 (retry) while an app is still coming up, the caller's code
        # otherwise: a stopped app is a real page about a real app, while an
        # unknown slug stays a 404 so crawlers and typos are not treated as found.
        status_code=status or (503 if retry else 200),
    )


def unknown_page(request: Request, slug: str, info: dict | None) -> Response:
    """Answer for ``/<prefix>/<slug>`` that maps to nothing runnable.

    Three distinct situations, deliberately separated: the app exists but is
    stopped, the app exists and never ran, or the slug is unknown. Telling an
    instructor "404" when a learner simply stopped their app is how a portal
    stops being trusted.
    """
    if info:
        status = _esc(str(info.get("status") or "stopped"))
        detail = (f"This app is <b>{status}</b>. Start it from the Deployment page "
                  f"and the address will serve it again - the path stays fixed.")
        code = 200
    else:
        detail = ("No app is published under this path yet. Deployed apps appear "
                  "here automatically the moment they start serving.")
        code = 404
    route = {"slug": slug, "name": (info or {}).get("name") or slug,
             "path": app_path(slug), "port": (info or {}).get("port")}
    if not _wants_html(request):
        return JSONResponse({"detail": f"No running app at /{app_path(slug)}",
                             "slug": slug,
                             "status": (info or {}).get("status", "unknown")},
                            status_code=code if code != 200 else 409)
    return _notice(request, route, title="Not live right now", detail=detail,
                   retry=None, status=code)


# --------------------------------------------------------------------------- #
# WebSockets (Streamlit needs this; Gradio uses it when available)
# --------------------------------------------------------------------------- #
def _ws_connect():
    """The best available WebSocket client across ``websockets`` versions.

    The package moved its asyncio client from ``websockets.legacy.client`` to
    ``websockets.asyncio.client`` and renamed the header argument along the way,
    so both spellings are resolved at runtime instead of pinning the app to one
    release.
    """
    try:  # websockets >= 13
        from websockets.asyncio.client import connect  # type: ignore

        return connect, "additional_headers"
    except ImportError:
        pass
    from websockets.legacy.client import connect  # type: ignore

    return connect, "extra_headers"


def _ws_headers(request: Request) -> dict[str, str]:
    """Headers to replay on the upstream handshake (Host/Origin decide Streamlit's
    own origin check, so they must survive)."""
    skip = HOP_BY_HOP | {"sec-websocket-accept", "sec-websocket-extensions",
                         "sec-websocket-key", "sec-websocket-version",
                         "accept-encoding"}
    return {k: v for k, v in request.headers.items() if k.lower() not in skip}


async def proxy_websocket(ws: WebSocket, route: dict) -> None:
    """Bridge a browser WebSocket to the app, both directions, until either ends.

    Frames are forwarded as received (bytes stay bytes) and no ping/pong is
    injected: the upstream app owns keep-alive for its own protocol, and a second
    heartbeat in the middle is what strands long model-training turns.
    """
    try:
        connect, header_kwarg = _ws_connect()
    except ImportError:  # pragma: no cover - optional dependency
        await ws.close(code=1011, reason="websocket proxy needs the 'websockets' package")
        return

    target = (f"ws://127.0.0.1:{route['port']}{ws.url.path}"
              + (f"?{ws.url.query}" if ws.url.query else ""))
    subprotocols = ws.scope.get("subprotocols") or []

    try:
        kwargs: dict[str, Any] = {
            "max_size": None, "ping_interval": None, "close_timeout": 5,
            header_kwarg: _ws_headers(ws),
        }
        if subprotocols:
            kwargs["subprotocols"] = list(subprotocols)
        upstream = await connect(target, **kwargs)
    except Exception as exc:  # noqa: BLE001 - any handshake failure is reported
        await ws.close(code=1011, reason=f"app not reachable: {exc}"[:120])
        return

    await ws.accept(subprotocol=(subprotocols[0] if subprotocols else None))

    async def client_to_app() -> None:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                await upstream.send(message["bytes"])
            elif message.get("text") is not None:
                await upstream.send(message["text"])

    async def app_to_client() -> None:
        async for frame in upstream:
            if isinstance(frame, (bytes, bytearray)):
                await ws.send_bytes(frame)
            else:
                await ws.send_text(frame)

    tasks = {asyncio.create_task(client_to_app()), asyncio.create_task(app_to_client())}
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        # Surface a real bridge bug instead of hiding it behind a clean shutdown.
        for task in done:
            if task.cancelled():
                continue
            exc = task.exception()
            if exc is not None and not isinstance(exc, WebSocketDisconnect):
                print(f"[atlas-proxy] websocket bridge ended: {exc!r}")
    except Exception:  # pragma: no cover - teardown races are expected
        pass
    finally:
        for task in tasks:
            task.cancel()
        try:
            await upstream.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            await ws.close()
        except Exception:  # noqa: BLE001 - already disconnected
            pass



def describe() -> dict:
    """Self-reporting, so the portal can say "live at /app/x" and be honest."""
    return {
        "enabled": bool(settings.deploy_builtin_proxy),
        "prefix": prefix(),
        "pattern": f"/{prefix()}/<slug>/",
        "websocket_bridge": True,
        "note": ("ATLAS routes each app's virtual directory to its internal "
                 "port; nginx is optional and only accelerates it."),
    }


__all__ = [
    "HOP_BY_HOP", "METHODS", "app_path", "describe", "prefix", "proxy_http",
    "proxy_websocket", "request_headers", "unknown_page", "upstream_target",
]
