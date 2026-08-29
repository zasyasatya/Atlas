"""Supervisors assigning topics to interns, and the reference pipeline catalogue.

Two related things live here because both answer "what is this intern allowed to
work on": the assignment CRUD a supervisor drives from the UI, and the read-only
pipeline browser the learning material links to.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel
from sqlmodel import select

from app.api.deps import CurrentUser, EditorUser, SessionDep
from app.domain.enums import Role
from app.domain.models import Assignment, Topic, User
from app.services import access, pipelines
from app.services.activity import record

router = APIRouter(prefix="/api", tags=["assignments"])


# ---------------------------------------------------------------- schemas
class AssignmentIn(BaseModel):
    user_id: int
    topic_id: int
    note: str = ""
    due_at: datetime | None = None


class BulkAssignmentIn(BaseModel):
    """Set an intern's whole topic list in one call - what the UI actually does."""
    user_id: int
    topic_ids: list[int]


class AssignmentOut(BaseModel):
    id: int
    user_id: int
    topic_id: int
    topic_slug: str
    topic_title: str
    user_email: str
    user_name: str
    note: str
    due_at: datetime | None
    created_at: datetime


def _out(session, row: Assignment) -> AssignmentOut:
    topic = session.get(Topic, row.topic_id)
    user = session.get(User, row.user_id)
    return AssignmentOut(
        id=row.id or 0, user_id=row.user_id, topic_id=row.topic_id,
        topic_slug=topic.slug if topic else "", topic_title=topic.title if topic else "",
        user_email=user.email if user else "", user_name=user.full_name if user else "",
        note=row.note, due_at=row.due_at, created_at=row.created_at)


# ---------------------------------------------------------------- my access
@router.get("/my-access")
def my_access(session: SessionDep, user: CurrentUser) -> dict:
    """What the signed-in person can see, and why.

    The UI uses this to explain an empty curriculum rather than showing a blank
    page - "no topics assigned yet" is a very different message from "loading".
    """
    return access.assignment_summary(session, user)


# ---------------------------------------------------------------- CRUD
@router.get("/assignments", response_model=list[AssignmentOut])
def list_assignments(session: SessionDep, user: CurrentUser,
                     user_id: int | None = None) -> list[AssignmentOut]:
    stmt = select(Assignment)
    if user_id is not None:
        stmt = stmt.where(Assignment.user_id == user_id)
    elif user.role not in access.UNRESTRICTED_ROLES:
        # An intern may only ever look at their own.
        stmt = stmt.where(Assignment.user_id == user.id)
    return [_out(session, r) for r in session.exec(stmt)]


@router.get("/assignable-users")
def assignable_users(session: SessionDep, user: EditorUser) -> list[dict]:
    """Interns a supervisor can assign work to, with their current load."""
    rows = session.exec(select(User).where(User.role == Role.INTERN)).all()
    out = []
    for u in rows:
        assigned = session.exec(
            select(Assignment).where(Assignment.user_id == u.id)).all()
        out.append({"id": u.id, "email": u.email, "full_name": u.full_name,
                    "cohort": u.cohort, "is_active": u.is_active,
                    "topic_ids": sorted(a.topic_id for a in assigned)})
    return sorted(out, key=lambda r: r["full_name"].lower())


@router.post("/assignments", response_model=AssignmentOut, status_code=201)
def create_assignment(payload: AssignmentIn, session: SessionDep,
                      user: EditorUser) -> AssignmentOut:
    target = session.get(User, payload.user_id)
    topic = session.get(Topic, payload.topic_id)
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if not topic:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Topic not found")

    existing = session.exec(
        select(Assignment).where(Assignment.user_id == payload.user_id,
                                 Assignment.topic_id == payload.topic_id)).first()
    if existing:
        return _out(session, existing)   # idempotent

    row = Assignment(user_id=payload.user_id, topic_id=payload.topic_id,
                     assigned_by=user.id or 0, note=payload.note,
                     due_at=payload.due_at)
    session.add(row)
    session.commit()
    session.refresh(row)
    record(session, user=user, action="assigned topic", entity_type="assignment",
           entity_id=row.id, topic_id=topic.id,
           detail=f"{topic.title} -> {target.full_name}")
    return _out(session, row)


@router.put("/assignments/bulk", response_model=list[AssignmentOut])
def set_assignments(payload: BulkAssignmentIn, session: SessionDep,
                    user: EditorUser) -> list[AssignmentOut]:
    """Replace one intern's assignments with exactly this list."""
    target = session.get(User, payload.user_id)
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    wanted = set(payload.topic_ids)
    valid = {t.id for t in session.exec(select(Topic)).all()}
    unknown = wanted - valid
    if unknown:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Unknown topic ids: {sorted(unknown)}")

    current = list(session.exec(
        select(Assignment).where(Assignment.user_id == payload.user_id)))
    have = {a.topic_id: a for a in current}

    for topic_id in have.keys() - wanted:
        session.delete(have[topic_id])
    for topic_id in wanted - have.keys():
        session.add(Assignment(user_id=payload.user_id, topic_id=topic_id,
                               assigned_by=user.id or 0))
    session.commit()

    record(session, user=user, action="updated assignments", entity_type="assignment",
           entity_id=payload.user_id,
           detail=f"{target.full_name}: {len(wanted)} topic(s)")

    return [_out(session, r) for r in session.exec(
        select(Assignment).where(Assignment.user_id == payload.user_id))]


@router.delete("/assignments/{assignment_id}", status_code=204, response_model=None)
def delete_assignment(assignment_id: int, session: SessionDep, user: EditorUser) -> None:
    row = session.get(Assignment, assignment_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    session.delete(row)
    session.commit()


# ---------------------------------------------------------------- pipelines
@router.get("/pipelines")
def list_pipelines(session: SessionDep, user: CurrentUser) -> list[dict]:
    """Reference implementations an intern can read without codebase access."""
    out = []
    for pipeline in pipelines.PIPELINES:
        if not pipelines.exists(pipeline):
            continue
        # A pipeline tied to a topic follows that topic's visibility.
        if pipeline.topic_slug and access.restricted(user):
            topic = session.exec(
                select(Topic).where(Topic.slug == pipeline.topic_slug)).first()
            if topic and not access.can_see_topic(session, user, topic.id):
                continue
        out.append(pipelines.summarise(pipeline))
    return out


def _resolve(session, user, slug: str):
    pipeline = pipelines.BY_SLUG.get(slug)
    if not pipeline or not pipelines.exists(pipeline):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pipeline not found")
    if pipeline.topic_slug and access.restricted(user):
        topic = session.exec(
            select(Topic).where(Topic.slug == pipeline.topic_slug)).first()
        if topic and not access.can_see_topic(session, user, topic.id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Pipeline not found")
    return pipeline


@router.get("/pipelines/{slug}")
def get_pipeline(slug: str, session: SessionDep, user: CurrentUser) -> dict:
    pipeline = _resolve(session, user, slug)
    return {
        **pipelines.summarise(pipeline),
        "files": [{"path": f.path, "size": f.size, "language": f.language}
                  for f in pipelines.list_files(pipeline)],
    }


@router.get("/pipelines/{slug}/file")
def get_pipeline_file(slug: str, path: str, session: SessionDep,
                      user: CurrentUser) -> dict:
    pipeline = _resolve(session, user, slug)
    try:
        text, language = pipelines.read_file(pipeline, path)
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found") from None
    return {"path": path, "language": language, "content": text}


@router.get("/pipelines/{slug}/download")
def download_pipeline(slug: str, session: SessionDep, user: CurrentUser) -> Response:
    pipeline = _resolve(session, user, slug)
    return Response(
        content=pipelines.build_zip(pipeline), media_type="application/zip",
        headers={"Content-Disposition":
                 f'attachment; filename="atlas_{pipeline.slug}.zip"'})
