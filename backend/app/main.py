"""ATLAS. FastAPI monolith serving the web UI, the API and every deployed app.

The product name and its tagline are configuration (``app.core.config``), not text
in this file, so rebranding never means editing code. This module is only about
wiring: routers, the brand endpoint, and the lifespan reconciliation.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routers import (approutes, assignments, assets, auth, content, dashboard,
                             deployments, notebooks, users)
from app.core.config import settings
from app.core.db import init_db, session_scope
from app.services import proxy
from app.services.deployments import running_routes
from app.services.seed import seed


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if settings.seed_demo_data:
        with session_scope() as session:
            seed(session)
    # Reconcile routing with the apps that are marked running, so a restarted
    # ATLAS regenerates the nginx virtual-directory config (and clears its own
    # slug cache) instead of leaving either pointing at ports from a previous boot.
    # Best-effort: a stale proxy must not stop the platform from coming up.
    try:
        with session_scope() as session:
            proxy.sync(running_routes(session))
    except Exception:
        pass
    yield


app = FastAPI(
    title=settings.app_name,
    description=settings.app_tagline,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (auth.router, content.router, assets.router, notebooks.router,
               deployments.router, dashboard.router, assignments.router, users.router):
    app.include_router(router)

# Deployed apps, mounted as virtual directories on this same port. Registered last
# among the routers but before the SPA catch-all below, so /app/<slug> is proxied
# to the app rather than falling through to the frontend bundle.
app.include_router(approutes.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment,
            "deploy_driver": settings.deploy_driver}


@app.get("/api/config")
def public_config() -> dict:
    return {
        "app_name": settings.app_name,
        # The single brand source the UI reads: name, tagline, short label,
        # subtitle, docs link. `app_name`/`tagline` stay at the top level for
        # anything already consuming them.
        "brand": settings.brand,
        "tagline": settings.app_tagline,
        # Lets the UI build an app's path ("/app/<slug>/") without hardcoding the
        # prefix, which is configurable per deployment.
        "app_prefix": settings.deploy_prefix,
        # The client id alone does not make sign-in work - the exchange needs
        # the secret too. Report whether the flow is actually usable so the UI
        # never offers a button that cannot succeed.
        "google_enabled": bool(settings.google_client_id and settings.google_client_secret),
        "google_client_id": settings.google_client_id,
        "colab_configured": bool(settings.github_token and settings.colab_github_repo),
        "kaggle_configured": bool(settings.kaggle_username and settings.kaggle_key),
        "deploy_driver": settings.deploy_driver,
        # Drives what the UI shows: production hides operator material
        # (setup commands, env vars, demo credentials) from end users.
        "environment": settings.environment,
        "is_production": settings.is_production,
    }


# ---- static frontend (Next.js static export) --------------------------------
STATIC = Path(settings.static_dir)
if (STATIC / "index.html").exists():
    app.mount("/_next", StaticFiles(directory=STATIC / "_next"), name="next-assets")

    # Asset extensions that must never fall back to index.html. Serving HTML in
    # place of a missing .js makes the browser fail to parse the chunk, React
    # never hydrates, and forms silently degrade to native submits.
    _ASSET_SUFFIXES = {
        ".js", ".mjs", ".css", ".map", ".json", ".txt", ".xml", ".woff", ".woff2",
        ".ttf", ".otf", ".eot", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
        ".avif", ".ico", ".webmanifest", ".wasm", ".mp4", ".webm",
    }

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)

        # Reject traversal (../) and absolute paths before touching the disk.
        try:
            candidate = (STATIC / full_path).resolve()
            candidate.relative_to(STATIC.resolve())
        except (ValueError, OSError):
            return JSONResponse({"detail": "Not Found"}, status_code=404)

        if candidate.is_file():
            return FileResponse(candidate)

        # A missing static asset is a real 404, never the SPA shell.
        if Path(full_path).suffix.lower() in _ASSET_SUFFIXES:
            return JSONResponse({"detail": "Not Found"}, status_code=404)

        html = STATIC / f"{full_path}.html" if full_path else STATIC / "index.html"
        if html.is_file():
            return FileResponse(html)
        index_html = STATIC / full_path / "index.html"
        if index_html.is_file():
            return FileResponse(index_html)
        return FileResponse(STATIC / "index.html")
else:
    @app.get("/", include_in_schema=False)
    def placeholder():
        # No bundle on disk: explain how to get one instead of a bare JSON blob.
        return HTMLResponse(
            """<!doctype html><html><head><meta charset="utf-8">
<title>ATLAS - frontend not built</title>
<style>body{font-family:ui-sans-serif,system-ui,sans-serif;background:#F6F8F6;color:#12160F;
display:grid;place-items:center;min-height:100vh;margin:0}
.c{max-width:540px;padding:40px;background:#fff;border:1px solid #E2E8E2;border-radius:20px}
h1{margin:0 0 8px;font-size:22px}p{color:#3E463A;line-height:1.6;font-size:14px}
code{background:#EEF2EE;padding:2px 7px;border-radius:6px;font-size:13px}
a{color:#487058}</style></head><body><div class="c">
<h1>API is running &mdash; UI not built yet</h1>
<p>The FastAPI backend is healthy, but no compiled frontend was found.</p>
<p>Build it with:</p><p><code>python run.py --build</code></p>
<p>That compiles the Next.js bundle into <code>backend/app/static/</code> and
serves everything from this one port.</p>
<p style="margin-top:22px"><a href="/api/docs">Open the API docs &rarr;</a></p>
</div></body></html>""",
            status_code=503,
        )
