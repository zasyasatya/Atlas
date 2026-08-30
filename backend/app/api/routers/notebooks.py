"""Notebook playground CRUD, run dispatch, and the remote-runtime callback API."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, File, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import JSONResponse, Response

from app.api.deps import CurrentUser, EditorUser, SessionDep
from app.services import access
from app.core.config import settings
from app.domain.enums import ComputeTarget, RunStatus
from app.domain.models import Asset, Notebook, Run, User
from app.domain.schemas import NotebookIn, NotebookOut, RunCallback, RunOut, RunRequest
from app.services import runs as run_service
from app.services.activity import record
from app.services.runners.bridge import build_bridge_cell

router = APIRouter(prefix="/api", tags=["playground"])


def _nb_out(nb: Notebook) -> NotebookOut:
    doc = json.loads(nb.content_json or "{}")
    return NotebookOut(
        id=nb.id or 0, topic_id=nb.topic_id, slug=nb.slug, title=nb.title,
        description=nb.description, default_target=nb.default_target,
        requires_gpu=nb.requires_gpu, requirements=nb.requirements, version=nb.version,
        updated_at=nb.updated_at, cell_count=len(doc.get("cells", [])),
    )


def _run_out(session, run: Run) -> RunOut:
    user = session.get(User, run.user_id)
    nb = session.get(Notebook, run.notebook_id)
    return RunOut(
        id=run.id or 0, notebook_id=run.notebook_id, topic_id=run.topic_id, target=run.target,
        status=run.status.value if hasattr(run.status, "value") else str(run.status),
        metrics=json.loads(run.metrics_json or "{}"), logs=run.logs or "",
        external_url=run.external_url, error=run.error, duration_seconds=run.duration_seconds,
        created_at=run.created_at, user_name=user.full_name if user else "",
        notebook_title=nb.title if nb else "",
    )


@router.get("/notebooks", response_model=list[NotebookOut])
def list_notebooks(session: SessionDep, user: CurrentUser, topic_id: int | None = None) -> list[NotebookOut]:
    from sqlmodel import select
    # Ordered by title: a topic whose playground is a numbered sequence ("1.
    # Preprocessing", "2. Training", ...) must list in that order, not in
    # whatever order the rows happen to have been inserted.
    stmt = select(Notebook).order_by(Notebook.topic_id, Notebook.title)
    if topic_id is not None:
        stmt = stmt.where(Notebook.topic_id == topic_id)
    rows = list(session.exec(stmt))
    if access.restricted(user):
        allowed = access.assigned_topic_ids(session, user.id or 0)
        rows = [nb for nb in rows if nb.topic_id in allowed]
    return [_nb_out(nb) for nb in rows]


@router.get("/notebooks/{notebook_id}")
def get_notebook(notebook_id: int, session: SessionDep, user: CurrentUser) -> dict:
    nb = session.get(Notebook, notebook_id)
    if not nb:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notebook not found")
    access.assert_topic_visible(session, user, nb.topic_id)
    return {**_nb_out(nb).model_dump(), "content": json.loads(nb.content_json or "{}")}


@router.post("/topics/{topic_id}/notebooks", response_model=NotebookOut, status_code=201)
def create_notebook(topic_id: int, payload: NotebookIn, session: SessionDep, user: EditorUser) -> NotebookOut:
    from app.api.routers.content import slugify
    nb = Notebook(
        topic_id=topic_id, slug=payload.slug or slugify(payload.title), title=payload.title,
        description=payload.description, default_target=payload.default_target,
        requires_gpu=payload.requires_gpu, requirements=payload.requirements,
        content_json=json.dumps(payload.content or {"cells": [], "metadata": {},
                                                    "nbformat": 4, "nbformat_minor": 5}),
        updated_by=user.id,
    )
    session.add(nb)
    session.commit()
    session.refresh(nb)
    record(session, user=user, action="created notebook", entity_type="notebook",
           entity_id=nb.id, topic_id=topic_id, detail=nb.title)
    return _nb_out(nb)


@router.put("/notebooks/{notebook_id}", response_model=NotebookOut)
def update_notebook(notebook_id: int, payload: NotebookIn, session: SessionDep, user: CurrentUser) -> NotebookOut:
    from datetime import datetime, timezone
    nb = session.get(Notebook, notebook_id)
    if not nb:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notebook not found")
    nb.title = payload.title or nb.title
    nb.description = payload.description or nb.description
    nb.requirements = payload.requirements
    nb.default_target = payload.default_target
    nb.requires_gpu = payload.requires_gpu
    if payload.content:
        nb.content_json = json.dumps(payload.content, ensure_ascii=False)
    nb.version += 1
    nb.updated_at = datetime.now(timezone.utc)
    nb.updated_by = user.id
    session.add(nb)
    session.commit()
    session.refresh(nb)
    return _nb_out(nb)


@router.get("/notebooks/{notebook_id}/export.ipynb")
def export_notebook(notebook_id: int, session: SessionDep, user: CurrentUser) -> Response:
    nb = session.get(Notebook, notebook_id)
    if not nb:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notebook not found")
    access.assert_topic_visible(session, user, nb.topic_id)
    return Response(content=nb.content_json, media_type="application/x-ipynb+json",
                    headers={"Content-Disposition": f'attachment; filename="{nb.slug}.ipynb"'})


# ---------------------------------------------------------------- runs

@router.post("/runs", response_model=dict, status_code=201)
def create_run(payload: RunRequest, session: SessionDep, user: CurrentUser) -> dict:
    nb = session.get(Notebook, payload.notebook_id)
    if not nb:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notebook not found")
    run, instructions = run_service.start_run(
        session, notebook=nb, user=user, target=payload.target,
        dataset_asset_id=payload.dataset_asset_id, params=payload.params,
    )
    record(session, user=user, action=f"launched run on {run.target.value}", entity_type="run",
           entity_id=run.id, topic_id=run.topic_id, detail=nb.title)
    return {"run": _run_out(session, run).model_dump(), "instructions": instructions,
            "upgraded": run.target != payload.target}


@router.get("/runs", response_model=list[RunOut])
def list_runs(session: SessionDep, user: CurrentUser, topic_id: int | None = None,
              mine: bool = False) -> list[RunOut]:
    rows = run_service.list_runs(session, topic_id=topic_id, user_id=user.id if mine else None)
    return [_run_out(session, r) for r in rows]


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: int, session: SessionDep, user: CurrentUser) -> RunOut:
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    return _run_out(session, run)


def _authorise_run(session, run_id: int, token: str | None) -> Run:
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    if not token or token != run.callback_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid run token")
    return run


@router.post("/runs/{run_id}/callback")
async def run_callback(run_id: int, payload: RunCallback, session: SessionDep,
                       x_atlas_token: str | None = Header(None)) -> dict:
    """Called by Colab / Kaggle notebooks through the injected atlas bridge."""
    run = _authorise_run(session, run_id, x_atlas_token)
    run_service.apply_callback(session, run, payload)
    return {"ok": True, "status": run.status}


@router.get("/runs/{run_id}/notebook.ipynb")
def run_notebook_source(run_id: int, session: SessionDep, token: str = Query("")) -> Response:
    """Serves the bridge-injected notebook so Colab can import it by URL."""
    run = _authorise_run(session, run_id, token)
    nb = session.get(Notebook, run.notebook_id)
    if not nb:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notebook not found")
    doc = json.loads(nb.content_json or "{}")
    api_base = settings.public_base_url or "http://127.0.0.1:8000"
    bridge = {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
              "source": build_bridge_cell(api_base, run_id, run.callback_token).splitlines(keepends=True)}
    doc["cells"] = [bridge] + doc.get("cells", [])
    doc.setdefault("metadata", {})["accelerator"] = "GPU"
    return Response(content=json.dumps(doc), media_type="application/x-ipynb+json")


@router.get("/runs/{run_id}/dataset")
def run_dataset(run_id: int, session: SessionDep, token: str = Query("")):
    from fastapi.responses import FileResponse
    run = _authorise_run(session, run_id, token)
    if not run.dataset_asset_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No dataset attached to this run")
    asset = session.get(Asset, run.dataset_asset_id)
    if not asset or not Path(asset.stored_path).exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset file missing")
    return FileResponse(asset.stored_path, filename=asset.filename)


@router.post("/runs/{run_id}/artifact")
async def upload_artifact(run_id: int, session: SessionDep, file: UploadFile = File(...),
                          token: str = Query("")) -> JSONResponse:
    from app.services.assets import store_asset
    from app.domain.enums import AssetKind
    run = _authorise_run(session, run_id, token)
    content = await file.read()
    asset = store_asset(session, filename=file.filename or f"artifact_run{run_id}.bin",
                        content=content, kind=AssetKind.ARTIFACT, user=session.get(User, run.user_id),
                        topic_id=run.topic_id, title=f"Run {run_id} - {file.filename}",
                        description=f"Artifact from run {run_id}", stage="model")
    return JSONResponse({"ok": True, "asset_id": asset.id})


@router.get("/compute/targets")
def compute_targets(user: CurrentUser) -> list[dict]:
    return [
        {"id": ComputeTarget.LOCAL_CPU.value, "label": "Platform CPU",
         "detail": "Built-in kernel. Instant, no setup. Light tabular / NLP work only.",
         "gpu": False, "available": True},
        {"id": ComputeTarget.COLAB_GPU.value, "label": "Google Colab GPU",
         "detail": "Free T4. One click, run all, metrics stream back automatically.",
         "gpu": True, "available": True,
         "configured": bool(settings.github_token and settings.colab_github_repo)},
        {"id": ComputeTarget.KAGGLE_GPU.value, "label": "Kaggle GPU",
         "detail": "Headless T4/P100, 30 h per week. Fully automatic - no browser tab needed.",
         "gpu": True, "available": bool(settings.kaggle_username and settings.kaggle_key),
         "configured": bool(settings.kaggle_username and settings.kaggle_key)},
    ]
