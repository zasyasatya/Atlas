"""One-click deployment + graduation rubric + public app portal."""
from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlmodel import desc, select

from app.api.deps import CurrentUser, EditorUser, SessionDep
from app.domain.enums import AppFramework, DeploymentStatus
from app.domain.models import Deployment, Topic, User
from app.domain.schemas import CheckOut, DeploymentIn, DeploymentOut
from app.services import compliance, deployments as deploy_service, proxy
from app.services.activity import record

router = APIRouter(prefix="/api/deployments", tags=["deployments"])


def _sync_proxy(session) -> dict:
    """Regenerate nginx virtual-directory config + reload, matching running apps.

    Runs after every deploy/stop/delete so nginx adjusts automatically. Never
    raises - a proxy issue must not break an otherwise successful deployment.
    """
    try:
        return proxy.sync(deploy_service.running_routes(session))
    except Exception as exc:  # pragma: no cover - defensive
        return {"status": "error", "detail": f"proxy sync failed: {exc}"}


def _out(session, dep: Deployment) -> DeploymentOut:
    owner = session.get(User, dep.user_id)
    topic = session.get(Topic, dep.topic_id)
    checks = compliance.checks_for(session, dep.id or 0)
    return DeploymentOut(
        id=dep.id or 0, name=dep.name, slug=dep.slug, topic_id=dep.topic_id,
        topic_title=topic.title if topic else "", user_id=dep.user_id,
        owner_name=owner.full_name if owner else "", framework=dep.framework,
        entrypoint=dep.entrypoint,
        status=dep.status.value if hasattr(dep.status, "value") else str(dep.status),
        url=dep.url, whimsical_url=dep.whimsical_url, readiness_score=dep.readiness_score,
        published_to_portal=dep.published_to_portal, build_logs=dep.build_logs,
        created_at=dep.created_at,
        checks=[CheckOut(rule_id=c.rule_id, label=c.label,
                         status=c.status.value if hasattr(c.status, "value") else str(c.status),
                         detail=c.detail, auto=c.auto) for c in checks],
    )


@router.get("", response_model=list[DeploymentOut])
def list_deployments(session: SessionDep, user: CurrentUser, topic_id: int | None = None,
                     mine: bool = False) -> list[DeploymentOut]:
    stmt = select(Deployment).order_by(desc(Deployment.created_at))
    if topic_id is not None:
        stmt = stmt.where(Deployment.topic_id == topic_id)
    if mine:
        stmt = stmt.where(Deployment.user_id == user.id)
    return [_out(session, d) for d in session.exec(stmt)]


TEMPLATE_ROOT = Path(__file__).resolve().parents[4] / "templates"


@router.get("/templates/{framework}", include_in_schema=True)
def download_template(framework: AppFramework) -> Response:
    """Ships a ready-to-edit starter that already satisfies all five rubric rules."""
    import io
    import zipfile

    folder = TEMPLATE_ROOT / f"{framework.value}_starter"
    if not folder.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not available")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(folder))
    buf.seek(0)
    return Response(
        content=buf.read(), media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="atlas_{framework.value}_starter.zip"'},
    )


@router.get("/rubric")
def rubric() -> list[dict]:
    return [{"id": r.id, "label": r.label, "hint": r.hint} for r in compliance.RULES]


@router.post("", response_model=DeploymentOut, status_code=201)
def create_deployment(payload: DeploymentIn, session: SessionDep, user: CurrentUser) -> DeploymentOut:
    base = deploy_service.slugify(payload.name)
    slug, i = base, 1
    while session.exec(select(Deployment).where(Deployment.slug == slug)).first():
        i += 1
        slug = f"{base}-{i}"
    dep = Deployment(topic_id=payload.topic_id, user_id=user.id or 0, name=payload.name,
                     slug=slug, framework=payload.framework, entrypoint=payload.entrypoint,
                     whimsical_url=payload.whimsical_url)
    session.add(dep)
    session.commit()
    session.refresh(dep)
    record(session, user=user, action="created deployment", entity_type="deployment",
           entity_id=dep.id, topic_id=dep.topic_id, detail=dep.name)
    return _out(session, dep)


@router.post("/{deployment_id}/bundle", response_model=DeploymentOut)
async def upload_bundle(deployment_id: int, session: SessionDep, user: CurrentUser,
                        file: UploadFile = File(...)) -> DeploymentOut:
    dep = session.get(Deployment, deployment_id)
    if not dep:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deployment not found")
    data = await file.read()
    root = deploy_service.unpack_bundle(dep, data, file.filename or "app.py")
    dep.bundle_path = str(root)
    entry = root / dep.entrypoint
    if not entry.exists():
        candidates = sorted(root.rglob("*.py"))
        preferred = [c for c in candidates if c.name in ("app.py", "main.py", "streamlit_app.py")]
        if preferred or candidates:
            chosen = (preferred or candidates)[0]
            dep.entrypoint = str(chosen.relative_to(root))
    session.add(dep)
    session.commit()
    topic = session.get(Topic, dep.topic_id)
    compliance.evaluate(session, dep, task_type=topic.task_type if topic else "classification")
    session.refresh(dep)
    record(session, user=user, action="uploaded app bundle", entity_type="deployment",
           entity_id=dep.id, topic_id=dep.topic_id, detail=f"{dep.name} ({file.filename})")
    return _out(session, dep)


@router.post("/{deployment_id}/check", response_model=DeploymentOut)
def run_checks(deployment_id: int, session: SessionDep, user: CurrentUser) -> DeploymentOut:
    dep = session.get(Deployment, deployment_id)
    if not dep:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deployment not found")
    topic = session.get(Topic, dep.topic_id)
    compliance.evaluate(session, dep, task_type=topic.task_type if topic else "classification")
    session.refresh(dep)
    return _out(session, dep)


@router.post("/{deployment_id}/deploy", response_model=DeploymentOut)
def deploy(deployment_id: int, session: SessionDep, user: CurrentUser) -> DeploymentOut:
    dep = session.get(Deployment, deployment_id)
    if not dep:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deployment not found")
    if not dep.bundle_path:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Upload the app bundle first")
    topic = session.get(Topic, dep.topic_id)
    dep.status = DeploymentStatus.BUILDING
    session.add(dep)
    session.commit()
    dep = deploy_service.deploy(session, dep, task_type=topic.task_type if topic else "classification")
    compliance.evaluate(session, dep, task_type=topic.task_type if topic else "classification")
    session.refresh(dep)
    if dep.status == DeploymentStatus.RUNNING:
        dep.published_to_portal = True
        session.add(dep)
        session.commit()
    # Make the new app reachable as a virtual directory and adjust nginx.
    pstat = _sync_proxy(session)
    if dep.status == DeploymentStatus.RUNNING:
        line = f"[proxy] {pstat.get('status')}: {pstat.get('detail') or pstat.get('conf_dir')}"
        dep.build_logs = (dep.build_logs or "") + "\n" + line
        session.add(dep)
        session.commit()
    record(session, user=user, action=f"deployed app ({dep.status})", entity_type="deployment",
           entity_id=dep.id, topic_id=dep.topic_id, detail=f"{dep.name} -> {dep.url or 'n/a'}")
    return _out(session, dep)


@router.post("/{deployment_id}/stop", response_model=DeploymentOut)
def stop(deployment_id: int, session: SessionDep, user: CurrentUser) -> DeploymentOut:
    dep = session.get(Deployment, deployment_id)
    if not dep:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deployment not found")
    deploy_service.stop(dep)
    dep.status = DeploymentStatus.STOPPED
    session.add(dep)
    session.commit()
    # Remove this app's virtual directory so nginx no longer routes its path.
    _sync_proxy(session)
    session.refresh(dep)
    return _out(session, dep)


@router.patch("/{deployment_id}", response_model=DeploymentOut)
def update_deployment(deployment_id: int, session: SessionDep, user: CurrentUser,
                      whimsical_url: str = Form(""), name: str = Form(""),
                      framework: AppFramework | None = Form(None),
                      entrypoint: str = Form("")) -> DeploymentOut:
    dep = session.get(Deployment, deployment_id)
    if not dep:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deployment not found")
    if whimsical_url:
        dep.whimsical_url = whimsical_url
    if name:
        dep.name = name
    if framework:
        dep.framework = framework
    if entrypoint:
        dep.entrypoint = entrypoint
    session.add(dep)
    session.commit()
    topic = session.get(Topic, dep.topic_id)
    compliance.evaluate(session, dep, task_type=topic.task_type if topic else "classification")
    session.refresh(dep)
    return _out(session, dep)


@router.get("/{deployment_id}/dockerfile")
def get_dockerfile(deployment_id: int, session: SessionDep, user: CurrentUser) -> Response:
    dep = session.get(Deployment, deployment_id)
    if not dep:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deployment not found")
    port = dep.internal_port or settings_port()
    base_path = deploy_service.base_url_path(dep.slug)
    root = Path(dep.bundle_path) if dep.bundle_path else None
    if root and root.exists():
        text = deploy_service.ensure_scaffold(root, dep.framework, dep.entrypoint,
                                              port, base_path)
    else:
        cmd = (deploy_service.STREAMLIT_CMD.format(entry=dep.entrypoint, port=port,
                                                   base_path=base_path)
               if dep.framework == AppFramework.STREAMLIT
               else deploy_service.GRADIO_CMD.format(entry=dep.entrypoint))
        health = (f"/{base_path}/_stcore/health"
                  if dep.framework == AppFramework.STREAMLIT else f"/{base_path}/")
        text = deploy_service.DOCKERFILE_TEMPLATE.format(port=port, cmd=cmd, health=health)
    return Response(content=text, media_type="text/plain",
                    headers={"Content-Disposition": 'attachment; filename="Dockerfile"'})


@router.get("/proxy-config")
def proxy_config(session: SessionDep, user: EditorUser) -> Response:
    """Full nginx vhost: every app as a virtual directory plus the portal proxy.

    The deployed apps share one domain/port (80/443); this is the reverse-proxy
    config that makes them reachable as virtual directories. In normal
    operation ATLAS writes and reloads this automatically - this endpoint is for
    operators setting nginx up for the first time or reviewing it. Only admins
    and supervisors (the operators who run nginx) need it.
    """
    routes = deploy_service.running_routes(session)
    text = proxy.full_vhost(routes)
    return Response(
        content=text, media_type="text/plain",
        headers={"Content-Disposition": 'attachment; filename="atlas.conf"'})


@router.get("/proxy-status")
def proxy_status(session: SessionDep, user: EditorUser) -> dict:
    """Live state of the automatic reverse proxy (nginx presence, snippets)."""
    stat = proxy.status()
    stat["routes"] = deploy_service.running_routes(session)
    return stat


def settings_port() -> int:
    from app.core.config import settings
    return settings.deploy_port_start


@router.delete("/{deployment_id}", status_code=204, response_model=None)
def delete_deployment(deployment_id: int, session: SessionDep, user: EditorUser) -> None:
    dep = session.get(Deployment, deployment_id)
    if not dep:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deployment not found")
    deploy_service.stop(dep)
    # Remove the app's isolated persistent data folder (it lives outside the
    # bundle, so it is not cleaned by unpack). Best-effort: never block a delete
    # on a data folder that is still held open.
    try:
        data_dir = deploy_service.app_data_dir(dep)
        if data_dir.exists():
            shutil.rmtree(data_dir, ignore_errors=True)
    except Exception:
        pass
    session.delete(dep)
    session.commit()
    # Drop the deleted app's virtual directory and reload nginx.
    _sync_proxy(session)
