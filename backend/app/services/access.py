"""Who can see which topic.

One rule, in one place, so the API and the UI can never disagree:

    Supervisors, admins and viewers      see every topic.
    Interns, in development              see every topic.
    Interns, in production               see only assigned topics.

Development stays open deliberately - a fresh install should be explorable
without first wiring up assignments. Production is the mode that enforces them,
and it fails closed: `Settings.is_production` treats anything unrecognised as
production, so a typo in ATLAS_ENVIRONMENT restricts access rather than
exposing it.

Restricting a *list* is not enough. Every endpoint that returns a single topic,
its lessons, its notebook or its assets has to apply the same check, or the
material is still one guessed URL away. `assert_topic_visible` is that check.
"""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlmodel import Session, select

from app.core.config import settings
from app.domain.enums import Role
from app.domain.models import Assignment, Topic, User

# Roles that are never restricted by assignment.
UNRESTRICTED_ROLES = {Role.ADMIN, Role.SUPERVISOR, Role.VIEWER}


def enforced() -> bool:
    """True when assignments actually gate access."""
    return settings.is_production


def restricted(user: User) -> bool:
    """True when this user only sees what they have been assigned."""
    return enforced() and user.role not in UNRESTRICTED_ROLES


def assigned_topic_ids(session: Session, user_id: int) -> set[int]:
    return {
        row.topic_id for row in session.exec(
            select(Assignment).where(Assignment.user_id == user_id)).all()
    }


def visible_topics(session: Session, user: User) -> list[Topic]:
    topics = list(session.exec(select(Topic).order_by(Topic.order_index)).all())
    if not restricted(user):
        return topics
    allowed = assigned_topic_ids(session, user.id or 0)
    return [t for t in topics if t.id in allowed]


def can_see_topic(session: Session, user: User, topic_id: int | None) -> bool:
    if topic_id is None:
        return True
    if not restricted(user):
        return True
    return topic_id in assigned_topic_ids(session, user.id or 0)


def assert_topic_visible(session: Session, user: User, topic_id: int | None) -> None:
    """Guard a single-object endpoint.

    Raises 404 rather than 403 on purpose: a 403 would confirm the topic exists,
    which leaks the shape of the curriculum to someone not enrolled in it.
    """
    if not can_see_topic(session, user, topic_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Topic not found")


def assignment_summary(session: Session, user: User) -> dict:
    """What the UI needs to explain the current state to the person looking."""
    total = len(list(session.exec(select(Topic)).all()))
    if not restricted(user):
        return {"enforced": enforced(), "restricted": False,
                "assigned_count": total, "total_topics": total}
    assigned = assigned_topic_ids(session, user.id or 0)
    return {"enforced": True, "restricted": True,
            "assigned_count": len(assigned), "total_topics": total}
