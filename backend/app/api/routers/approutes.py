"""Mounts every deployed app's virtual directory on the ATLAS port itself.

`app.services.proxy` writes nginx config. This module makes that config
*optional*: the same ``/<prefix>/<slug>/`` path is answered by ATLAS and forwarded
to the app's internal port, so "deploy" and "open in a new tab" are enough -
nothing has to be installed, copied or reloaded for an app to work.

Routing is by slug, resolved from the database and cached for a moment
(``ATLAS_DEPLOY_ROUTE_TTL_SECONDS``). The cache is what makes this cheap enough to
put in front of a page that asks for forty assets: an app is only ever looked up
once per TTL, and the TTL is short enough that a deploy or a stop is reflected
almost immediately. ``invalidate()`` is called from the deployment endpoints so
the same request that started an app can already serve it.

Access: a virtual directory is unauthenticated, exactly like the generated nginx
config and like every other "here is my deployed app" link. A slug is not a
secret, so treat a running app as public to anyone who can reach the host; put
real auth in front (nginx auth_request, a VPN) if that is not what you want.
"""
from __future__ import annotations

import time
from typing import Callable

from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import JSONResponse, RedirectResponse
from sqlmodel import select

from app.core.config import settings
from app.core.db import session_scope
from app.domain.enums import DeploymentStatus
from app.domain.models import Deployment
from app.services import app_proxy

# slug -> (monotonic time, route or None). None is cached too: a probe of a slug
# that does not exist (a browser requesting /app/favicon.ico, a scanner) must not
# turn into a database query per request.
_cache: dict[str, tuple[float, dict | None]] = {}

_BARE_METHODS = ["GET", "HEAD"]


def _route_of(dep: Deployment) -> dict:
    """Everything the proxy needs to know about one deployment."""
    return {
        "slug": dep.slug,
        "name": dep.name,
        "path": app_proxy.app_path(dep.slug),
        "port": dep.internal_port,
        "framework": dep.framework.value if hasattr(dep.framework, "value")
                      else str(dep.framework),
        "status": dep.status.value if hasattr(dep.status, "value") else str(dep.status),
    }


def invalidate(slug: str | None = None) -> None:
    """Drop cached routes so the next request re-reads the database."""
    if slug is None:
        _cache.clear()
    else:
        _cache.pop(slug, None)


def resolve(slug: str) -> dict | None:
    """Look up ``slug``: a runnable route, or a description of why it is not.

    The returned dict always carries ``status``; it only carries a usable
    ``port`` when the app is actually running, which is what lets the proxy show a
    truthful page instead of a bare 502.
    """
    ttl = max(0.0, float(settings.deploy_route_ttl_seconds))
    hit = _cache.get(slug)
    now = time.monotonic()
    if hit is not None and now - hit[0] < ttl:
        return hit[1]

    route: dict | None = None
    try:
        with session_scope() as session:
            dep = session.exec(select(Deployment).where(Deployment.slug == slug)).first()
            if dep is not None:
                route = _route_of(dep)
                if dep.status != DeploymentStatus.RUNNING or not dep.internal_port:
                    route["port"] = None
    except Exception:  # pragma: no cover - a broken lookup must not be a 500
        route = None
    _cache[slug] = (now, route)
    return route


def _disabled(prefix: str, slug: str):
    """Answer for when an operator turned the built-in proxy off.

    Saying so beats a silent 404: the request looks like a broken app while the
    actual fix is one environment variable (or an nginx that owns the path).
    """
    return JSONResponse(
        {
            "detail": (f"The built-in virtual-directory proxy is disabled "
                       f"(ATLAS_DEPLOY_BUILTIN_PROXY=false), so /{prefix}/{slug} is "
                       f"expected to be served by an external reverse proxy."),
            "slug": slug,
            "help": "Set ATLAS_DEPLOY_BUILTIN_PROXY=true to let ATLAS route apps itself.",
        },
        status_code=404,
    )


def build_router(prefix: str | None = None,
                 resolver: Callable[[str], dict | None] | None = None) -> APIRouter:
    """The virtual-directory router.

    Split out from a module-level instance so a caller (and the test suite) can
    mount it with a chosen prefix and a stub resolver instead of a database.
    """
    p = (prefix or app_proxy.prefix()).strip("/")
    lookup = resolver or resolve
    router = APIRouter(include_in_schema=False)
    bare = f"/{p}/{{slug}}"
    deep = f"/{p}/{{slug}}/{{rest:path}}"

    async def serve(request: Request, slug: str) -> object:
        """Proxy a running app, otherwise explain what is in the way."""
        if not settings.deploy_builtin_proxy:
            # The operator owns routing (an nginx that listens on the port
            # directly), so do not shadow it - say so instead of pretending.
            return _disabled(p, slug)
        info = lookup(slug)
        if not info or not info.get("port"):
            return app_proxy.unknown_page(request, slug, info)
        return await app_proxy.proxy_http(request, info)

    @router.api_route(bare, methods=_BARE_METHODS)
    async def bare_hit(request: Request, slug: str):
        if not settings.deploy_builtin_proxy:
            return _disabled(p, slug)
        info = lookup(slug)
        if not info or not info.get("port"):
            return app_proxy.unknown_page(request, slug, info)
        # Trailing slash matters: the app was launched with this exact base path,
        # so relative asset URLs only resolve below the slash.
        return RedirectResponse(url=f"/{p}/{slug}/", status_code=307)

    @router.api_route(deep, methods=list(app_proxy.METHODS))
    async def deep_hit(request: Request, slug: str, rest: str = ""):
        response = await serve(request, slug)
        if isinstance(response, RedirectResponse):
            return response
        try:
            response.headers.setdefault("x-atlas-app", slug)
        except AttributeError:  # pragma: no cover - non-Response guard
            pass
        return response

    @router.websocket(f"/{p}/{{slug}}/{{rest:path}}")
    async def ws_hit(ws: WebSocket, slug: str, rest: str = ""):
        info = lookup(slug)
        if not info or not info.get("port"):
            await ws.close(code=1011, reason="app is not running")
            return
        await app_proxy.proxy_websocket(ws, info)

    return router


router = build_router()
