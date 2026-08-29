"""ATLAS - AI Internship Operating System. FastAPI monolith serving the Next.js bundle."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routers import assets, auth, content, dashboard, deployments, notebooks
from app.core.config import settings
from app.core.db import init_db, session_scope
from app.services.seed import seed


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if settings.seed_demo_data:
        with session_scope() as session:
            seed(session)
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
               deployments.router, dashboard.router):
    app.include_router(router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment,
            "deploy_driver": settings.deploy_driver}


@app.get("/api/config")
def public_config() -> dict:
    return {
        "app_name": settings.app_name,
        "tagline": settings.app_tagline,
        "google_client_id": settings.google_client_id,
        "colab_configured": bool(settings.github_token and settings.colab_github_repo),
        "kaggle_configured": bool(settings.kaggle_username and settings.kaggle_key),
        "deploy_driver": settings.deploy_driver,
    }


# ---- static frontend (Next.js static export) --------------------------------
STATIC = Path(settings.static_dir)
if (STATIC / "index.html").exists():
    app.mount("/_next", StaticFiles(directory=STATIC / "_next"), name="next-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = STATIC / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        html = STATIC / f"{full_path}.html" if full_path else STATIC / "index.html"
        if html.is_file():
            return FileResponse(html)
        index_html = STATIC / full_path / "index.html"
        if index_html.is_file():
            return FileResponse(index_html)
        return FileResponse(STATIC / "index.html")
else:
    @app.get("/", include_in_schema=False)
    def placeholder() -> dict:
        return {"message": f"{settings.app_name} API is running. Frontend bundle not built yet.",
                "docs": "/api/docs"}
