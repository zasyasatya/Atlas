"""Dataset / PPT deck upload, versioned history, preview."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import CurrentUser, EditorUser, SessionDep
from app.domain.enums import AssetKind
from app.domain.models import Asset, User
from app.domain.schemas import AssetOut
from app.services import assets as asset_service
from app.services.activity import record

router = APIRouter(prefix="/api/assets", tags=["assets"])

MAX_BYTES = 200 * 1024 * 1024


def _out(session, asset: Asset) -> AssetOut:
    uploader = session.get(User, asset.uploaded_by) if asset.uploaded_by else None
    return AssetOut(
        id=asset.id or 0, topic_id=asset.topic_id, kind=asset.kind.value, title=asset.title,
        description=asset.description, filename=asset.filename, size_bytes=asset.size_bytes,
        version=asset.version, stage=asset.stage, row_count=asset.row_count,
        column_count=asset.column_count, slide_count=asset.slide_count,
        preview=json.loads(asset.preview_json or "{}"),
        uploader_name=uploader.full_name if uploader else "unknown",
        created_at=asset.created_at,
    )


@router.get("", response_model=list[AssetOut])
def list_assets(session: SessionDep, user: CurrentUser,
                topic_id: int | None = None, kind: AssetKind | None = None) -> list[AssetOut]:
    return [_out(session, a) for a in asset_service.list_assets(session, topic_id=topic_id, kind=kind)]


@router.post("", response_model=AssetOut, status_code=status.HTTP_201_CREATED)
async def upload_asset(
    session: SessionDep,
    user: CurrentUser,
    file: UploadFile = File(...),
    kind: AssetKind = Form(AssetKind.DATASET),
    topic_id: int | None = Form(None),
    title: str = Form(""),
    description: str = Form(""),
    stage: str = Form("raw"),
) -> AssetOut:
    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File exceeds 200 MB limit")
    asset = asset_service.store_asset(
        session, filename=file.filename or "upload.bin", content=content, kind=kind, user=user,
        topic_id=topic_id, title=title, description=description, stage=stage,
        content_type=file.content_type or "",
    )
    record(session, user=user, action=f"uploaded {kind.value}", entity_type="asset",
           entity_id=asset.id, topic_id=topic_id, detail=f"{asset.title} (v{asset.version})")
    return _out(session, asset)


@router.get("/{asset_id}/download")
def download_asset(asset_id: int, session: SessionDep, user: CurrentUser) -> FileResponse:
    asset = session.get(Asset, asset_id)
    if not asset or not Path(asset.stored_path).exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found")
    return FileResponse(asset.stored_path, filename=asset.filename)


@router.delete("/{asset_id}", status_code=204, response_model=None)
def delete_asset(asset_id: int, session: SessionDep, user: EditorUser) -> None:
    asset = session.get(Asset, asset_id)
    if not asset:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found")
    Path(asset.stored_path).unlink(missing_ok=True)
    session.delete(asset)
    session.commit()
    record(session, user=user, action="deleted asset", entity_type="asset",
           topic_id=asset.topic_id, detail=asset.title)
