"""Run orchestration: pick a runner, dispatch, absorb callbacks."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlmodel import Session, desc, select

from app.core.security import new_run_token
from app.domain.enums import ComputeTarget, RunStatus
from app.domain.models import Notebook, Run, User
from app.services.runners.colab_gpu import ColabRunner
from app.services.runners.kaggle_gpu import KaggleRunner
from app.services.runners.local_cpu import LocalCpuRunner

_RUNNERS = {
    ComputeTarget.LOCAL_CPU: LocalCpuRunner(),
    ComputeTarget.COLAB_GPU: ColabRunner(),
    ComputeTarget.KAGGLE_GPU: KaggleRunner(),
}


def resolve_target(requested: ComputeTarget, notebook: Notebook) -> ComputeTarget:
    """Heavy CV notebooks must never silently land on the CPU worker."""
    if notebook.requires_gpu and requested == ComputeTarget.LOCAL_CPU:
        return notebook.default_target if notebook.default_target != ComputeTarget.LOCAL_CPU else ComputeTarget.COLAB_GPU
    return requested


def start_run(
    session: Session,
    *,
    notebook: Notebook,
    user: User,
    target: ComputeTarget,
    dataset_asset_id: int | None = None,
    params: dict | None = None,
) -> tuple[Run, list[str]]:
    effective = resolve_target(target, notebook)
    run = Run(
        notebook_id=notebook.id or 0,
        topic_id=notebook.topic_id,
        user_id=user.id or 0,
        target=effective,
        status=RunStatus.PENDING,
        dataset_asset_id=dataset_asset_id,
        params_json=json.dumps(params or {}),
        callback_token=new_run_token(),
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    runner = _RUNNERS[effective]
    result = runner.launch(run, notebook)
    run.status = result.status
    run.external_url = result.external_url
    run.logs = result.logs
    run.error = result.error
    if result.status in (RunStatus.RUNNING, RunStatus.QUEUED):
        run.started_at = datetime.now(timezone.utc)
    session.add(run)
    session.commit()
    session.refresh(run)
    return run, result.instructions


def apply_callback(session: Session, run: Run, payload) -> Run:
    if payload.logs:
        run.logs = ((run.logs or "") + "\n" + payload.logs)[-20000:]
    if payload.metrics:
        current = json.loads(run.metrics_json or "{}")
        current.update(payload.metrics)
        run.metrics_json = json.dumps(current, default=str)
    if payload.external_url:
        run.external_url = payload.external_url
    if payload.status:
        run.status = RunStatus(payload.status) if payload.status in RunStatus.__members__.values() else run.status
    if payload.error:
        run.error = payload.error[:4000]
        run.status = RunStatus.FAILED
    if run.status in (RunStatus.SUCCEEDED, RunStatus.FAILED):
        run.finished_at = datetime.now(timezone.utc)
        if run.started_at:
            start = run.started_at if run.started_at.tzinfo else run.started_at.replace(tzinfo=timezone.utc)
            run.duration_seconds = round((run.finished_at - start).total_seconds(), 2)
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def list_runs(session: Session, *, topic_id: int | None = None, user_id: int | None = None, limit: int = 60):
    stmt = select(Run).order_by(desc(Run.created_at)).limit(limit)
    if topic_id is not None:
        stmt = stmt.where(Run.topic_id == topic_id)
    if user_id is not None:
        stmt = stmt.where(Run.user_id == user_id)
    return list(session.exec(stmt))
