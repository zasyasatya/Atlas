"""Dashboard aggregates + activity feed."""
from __future__ import annotations

from fastapi import APIRouter
from sqlmodel import func, select

from app.api.deps import CurrentUser, SessionDep
from app.domain.enums import DeploymentStatus, RunStatus
from app.domain.models import (
    ActivityLog,
    Asset,
    Deployment,
    Lesson,
    Notebook,
    Progress,
    Run,
    Topic,
    User,
)
from app.domain.schemas import ActivityOut
from app.services.activity import recent

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
def dashboard(session: SessionDep, user: CurrentUser) -> dict:
    count = lambda model, *w: session.exec(select(func.count()).select_from(model).where(*w)).one() if w \
        else session.exec(select(func.count()).select_from(model)).one()

    my_progress = session.exec(select(Progress).where(Progress.user_id == user.id,
                                                      Progress.completed == True)).all()  # noqa: E712
    xp = sum(p.xp_earned for p in my_progress)
    total_lessons = count(Lesson)
    runs = session.exec(select(Run)).all()
    deps = session.exec(select(Deployment)).all()
    gpu_runs = [r for r in runs if r.target != "local_cpu"]
    ready = [d for d in deps if d.readiness_score >= 80]

    return {
        "user": {"name": user.full_name, "role": user.role, "cohort": user.cohort,
                 "xp": xp, "level": 1 + xp // 200,
                 "lessons_done": len(my_progress), "lessons_total": total_lessons},
        "counters": {
            "topics": count(Topic), "notebooks": count(Notebook),
            "datasets": count(Asset, Asset.kind == "dataset"),
            "decks": count(Asset, Asset.kind == "deck"),
            "runs": len(runs), "gpu_runs": len(gpu_runs),
            "deployments": len(deps),
            "live_apps": len([d for d in deps if d.status == DeploymentStatus.RUNNING]),
            "graduation_ready": len(ready),
            "interns": count(User, User.role == "intern"),
        },
        "run_status": {
            s.value: len([r for r in runs if r.status == s]) for s in RunStatus
        },
        "recent_runs": [
            {"id": r.id, "status": r.status, "target": r.target, "topic_id": r.topic_id,
             "created_at": r.created_at.isoformat()}
            for r in sorted(runs, key=lambda x: x.created_at, reverse=True)[:6]
        ],
    }


@router.get("/activity", response_model=list[ActivityOut])
def activity(session: SessionDep, user: CurrentUser, limit: int = 30,
             topic_id: int | None = None) -> list[ActivityOut]:
    return [ActivityOut(id=a.id or 0, actor_name=a.actor_name, action=a.action,
                        entity_type=a.entity_type, detail=a.detail, topic_id=a.topic_id,
                        created_at=a.created_at)
            for a in recent(session, limit=limit, topic_id=topic_id)]


@router.get("/leaderboard")
def leaderboard(session: SessionDep, user: CurrentUser) -> list[dict]:
    rows = session.exec(select(Progress).where(Progress.completed == True)).all()  # noqa: E712
    tally: dict[int, int] = {}
    for row in rows:
        tally[row.user_id] = tally.get(row.user_id, 0) + row.xp_earned
    out = []
    for uid, xp in sorted(tally.items(), key=lambda kv: kv[1], reverse=True)[:10]:
        u = session.get(User, uid)
        if u:
            out.append({"name": u.full_name, "cohort": u.cohort, "xp": xp, "level": 1 + xp // 200})
    return out
