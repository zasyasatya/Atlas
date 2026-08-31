"""Admin/supervisor user management: list, add, and maintain accounts.

The rest of ATLAS lets people in through self sign-in (Google SSO) or seeded
demo accounts. This router is the operator path for creating accounts up
front - interns, viewers, even additional supervisors - before anyone needs to
sign in. It is deliberately guarded: only admins can create or promote other
admins/supervisors, and nobody may edit an account with equal or greater
privilege than their own.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlmodel import select

from app.api.deps import CurrentUser, EditorUser, SessionDep
from app.core.security import hash_password
from app.domain.enums import Role
from app.domain.models import User
from app.services.activity import record

router = APIRouter(prefix="/api/users", tags=["users"])


# ----------------------------------------------------------------- schemas
class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    role: Role = Role.INTERN
    cohort: str = ""


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    role: Role | None = None
    cohort: str | None = None
    is_active: bool | None = None


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: Role
    cohort: str = ""
    is_active: bool = True
    created_at: datetime


def _out(u: User) -> UserOut:
    return UserOut(id=u.id or 0, email=u.email, full_name=u.full_name, role=u.role,
                   cohort=u.cohort, is_active=u.is_active, created_at=u.created_at)


def _may_manage(actor: User, target_role: Role) -> bool:
    """Only admins create or change admins/supervisors.

    A supervisor runs the intern-facing platform, so they may add interns and
    viewers freely, but they must not be able to mint more supervisors or touch
    an administrator.
    """
    if actor.role == Role.ADMIN:
        return True
    return target_role in (Role.INTERN, Role.VIEWER)


def _guard_target(actor: User, target: User) -> None:
    """Refuse an edit when it would change a more privileged account."""
    if actor.role != Role.ADMIN and target.role == Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Only an admin can manage administrator accounts")


# ------------------------------------------------------------------- list
@router.get("", response_model=list[UserOut])
def list_users(session: SessionDep, user: EditorUser) -> list[UserOut]:
    """Every account, for the operator's people directory."""
    rows = session.exec(select(User).order_by(User.created_at.desc())).all()
    return [_out(u) for u in rows]


# ------------------------------------------------------------------ create
@router.post("", response_model=UserOut, status_code=201)
def create_user(payload: UserCreate, session: SessionDep, user: EditorUser) -> UserOut:
    if not _may_manage(user, payload.role):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Your role cannot create a '{payload.role.value}' account")

    email = payload.email.strip().lower()
    existing = session.exec(select(User).where(User.email == email)).first()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "A user with that email already exists")

    new_user = User(
        email=email,
        full_name=payload.full_name.strip(),
        hashed_password=hash_password(payload.password),
        role=payload.role,
        cohort=payload.cohort.strip(),
        is_active=True,
    )
    session.add(new_user)
    session.commit()
    session.refresh(new_user)

    record(session, user=user, action="created user", entity_type="user",
           entity_id=new_user.id,
           detail=f"{new_user.full_name} ({new_user.email}) as {new_user.role.value}")
    return _out(new_user)


# ------------------------------------------------------------------ update
@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdate, session: SessionDep,
                user: EditorUser) -> UserOut:
    target = session.get(User, user_id)
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    _guard_target(user, target)

    if payload.full_name is not None:
        target.full_name = payload.full_name.strip()
    if payload.cohort is not None:
        target.cohort = payload.cohort.strip()
    if payload.password:
        target.hashed_password = hash_password(payload.password)
    if payload.role is not None and payload.role != target.role:
        if not _may_manage(user, payload.role):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Your role cannot grant the '{payload.role.value}' role")
        _guard_target(user, target)  # guard again against self-demotion
        target.role = payload.role
    if payload.is_active is not None:
        target.is_active = payload.is_active

    session.add(target)
    session.commit()
    session.refresh(target)

    record(session, user=user, action="updated user", entity_type="user",
           entity_id=target.id, detail=f"{target.full_name} ({target.email})")
    return _out(target)
