"""Authentication: local password + Google OAuth token exchange."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, status
from sqlmodel import select

from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.domain.enums import Role
from app.domain.models import User
from app.domain.schemas import GoogleLoginRequest, LoginRequest, TokenResponse, UserOut
from app.api.deps import CurrentUser, SessionDep

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _token_for(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.email, user.role.value),
        user=UserOut(id=user.id or 0, email=user.email, full_name=user.full_name,
                     role=user.role, cohort=user.cohort, avatar_url=user.avatar_url),
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, session: SessionDep) -> TokenResponse:
    user = session.exec(select(User).where(User.email == payload.email)).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    return _token_for(user)


@router.post("/google", response_model=TokenResponse)
async def google_login(payload: GoogleLoginRequest, session: SessionDep) -> TokenResponse:
    email, name, sub = payload.email, payload.full_name, payload.sub
    if payload.id_token:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get("https://oauth2.googleapis.com/tokeninfo",
                                    params={"id_token": payload.id_token})
        if resp.status_code != 200:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid Google token")
        info = resp.json()
        if settings.google_client_id and info.get("aud") != settings.google_client_id:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token audience mismatch")
        email, name, sub = info.get("email"), info.get("name", ""), info.get("sub", "")
    if not email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email required")

    user = session.exec(select(User).where(User.email == email)).first()
    if not user:
        user = User(email=email, full_name=name or email.split("@")[0], role=Role.INTERN,
                    google_sub=sub, hashed_password=hash_password(sub or email))
        session.add(user)
        session.commit()
        session.refresh(user)
    return _token_for(user)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut(id=user.id or 0, email=user.email, full_name=user.full_name,
                   role=user.role, cohort=user.cohort, avatar_url=user.avatar_url)


@router.get("/demo-accounts")
def demo_accounts() -> list[dict]:
    return [
        {"email": "supervisor@atlas.id", "password": "supervisor123", "role": "supervisor"},
        {"email": "intern@atlas.id", "password": "intern123", "role": "intern"},
        {"email": "admin@atlas.id", "password": "admin123", "role": "admin"},
    ]
