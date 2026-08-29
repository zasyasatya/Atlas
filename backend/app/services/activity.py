"""Central activity/audit trail."""
from __future__ import annotations

from sqlmodel import Session, desc, select

from app.domain.models import ActivityLog, User


def record(
    session: Session,
    *,
    user: User | None,
    action: str,
    entity_type: str = "",
    entity_id: int | None = None,
    topic_id: int | None = None,
    detail: str = "",
) -> ActivityLog:
    log = ActivityLog(
        user_id=user.id if user else None,
        actor_name=user.full_name if user else "system",
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        topic_id=topic_id,
        detail=detail,
    )
    session.add(log)
    session.commit()
    session.refresh(log)
    return log


def recent(session: Session, limit: int = 40, topic_id: int | None = None) -> list[ActivityLog]:
    stmt = select(ActivityLog).order_by(desc(ActivityLog.created_at)).limit(limit)
    if topic_id is not None:
        stmt = stmt.where(ActivityLog.topic_id == topic_id)
    return list(session.exec(stmt))
