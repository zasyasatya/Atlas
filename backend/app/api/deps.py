"""Shared FastAPI dependencies: auth + role guards."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlmodel import Session, select

from app.core.db import get_session
from app.core.security import decode_access_token
from app.domain.enums import Role
from app.domain.models import User

SessionDep = Annotated[Session, Depends(get_session)]


def get_current_user(
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    payload = decode_access_token(authorization.split(" ", 1)[1])
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = session.exec(select(User).where(User.email == payload.get("sub"))).first()
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: Role):
    def guard(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                f"Requires role: {', '.join(r.value for r in roles)}")
        return user
    return guard


EditorUser = Annotated[User, Depends(require_roles(Role.ADMIN, Role.SUPERVISOR))]
