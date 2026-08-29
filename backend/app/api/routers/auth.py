"""Authentication: local password + Google OAuth 2.0 (authorization code + PKCE)."""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from urllib.parse import quote, urlencode

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import select

from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.domain.enums import Role
from app.domain.models import User
from app.domain.schemas import LoginRequest, TokenResponse, UserOut
from app.api.deps import CurrentUser, SessionDep
from app.services import google_oauth
from app.services.google_oauth import OAuthError

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
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account is disabled")
    return _token_for(user)


# ---------------------------------------------------------------------------
# Google OAuth
# ---------------------------------------------------------------------------
@dataclass
class _PendingLogin:
    """One in-flight sign-in. Single-use and short-lived."""
    verifier: str
    nonce: str
    redirect_uri: str
    next_path: str
    created_at: float = field(default_factory=time.time)


# In-process store. ATLAS is a single-container monolith, so this is adequate
# and avoids a Redis dependency; entries live for minutes and are consumed on
# first use. Behind multiple replicas this would need shared storage - noted in
# docs/SYSTEM_DESIGN.md.
_pending: dict[str, _PendingLogin] = {}
_STATE_TTL = 600.0          # 10 minutes to complete a sign-in
_MAX_PENDING = 512


def _sweep() -> None:
    now = time.time()
    for key in [k for k, v in _pending.items() if now - v.created_at > _STATE_TTL]:
        _pending.pop(key, None)
    # Bound memory even if something goes wrong upstream.
    if len(_pending) > _MAX_PENDING:
        for key in sorted(_pending, key=lambda k: _pending[k].created_at)[:len(_pending) - _MAX_PENDING]:
            _pending.pop(key, None)


def _google_enabled() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def _allowed_domains() -> set[str]:
    raw = (settings.google_allowed_domains or "").strip()
    return {d.strip().lower() for d in raw.split(",") if d.strip()} if raw else set()


def _base_url(request: Request) -> str:
    """The externally reachable origin.

    Behind Coolify/nginx the app sees http://0.0.0.0:8000, so an explicit
    ATLAS_PUBLIC_BASE_URL wins. Otherwise trust the proxy headers uvicorn has
    already normalised (--proxy-headers).
    """
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    return str(request.base_url).rstrip("/")


def _redirect_uri(request: Request) -> str:
    return f"{_base_url(request)}/api/auth/google/callback"


def _safe_next(raw: str) -> str:
    """Only allow same-site paths, so `next` cannot become an open redirect."""
    if not raw.startswith("/") or raw.startswith("//"):
        return "/dashboard"
    return raw


@router.get("/google/start")
def google_start(request: Request, next: str = "/dashboard") -> RedirectResponse:
    """Begin sign-in: mint PKCE + state, then bounce the browser to Google."""
    if not _google_enabled():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Google sign-in is not configured on this server")
    _sweep()

    verifier, challenge = google_oauth.make_pkce_pair()
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(24)
    redirect_uri = _redirect_uri(request)

    _pending[state] = _PendingLogin(verifier=verifier, nonce=nonce,
                                    redirect_uri=redirect_uri,
                                    next_path=_safe_next(next))

    return RedirectResponse(
        google_oauth.build_authorize_url(
            client_id=settings.google_client_id, redirect_uri=redirect_uri,
            state=state, code_challenge=challenge, nonce=nonce),
        status_code=status.HTTP_307_TEMPORARY_REDIRECT)


def _closing_page(message: str, ok: bool) -> HTMLResponse:
    """Rendered only on failure, so the user is not dumped on a blank JSON page."""
    colour = "#487058" if ok else "#B4533F"
    safe = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return HTMLResponse(
        f"""<!doctype html><html><head><meta charset="utf-8">
<title>Sign-in</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#F6F8F6;
   font:15px/1.6 ui-sans-serif,system-ui,-apple-system,'Segoe UI',sans-serif;color:#12160F}}
 .card{{max-width:26rem;padding:2rem;background:#fff;border:1px solid #E2E8E2;border-radius:20px;
   text-align:center;box-shadow:0 1px 2px rgba(0,0,0,.04)}}
 h1{{margin:0 0 .5rem;font-size:1.05rem;color:{colour}}}
 p{{margin:0 0 1.25rem;color:#3E463A;font-size:14px}}
 a{{display:inline-block;padding:.6rem 1.1rem;border-radius:12px;background:#5B8C6E;color:#fff;
   text-decoration:none;font-weight:600;font-size:13px}}
</style></head><body><div class="card">
<h1>{'Signed in' if ok else 'Sign-in failed'}</h1><p>{safe}</p>
<a href="/login">Back to sign in</a></div></body></html>""",
        status_code=200 if ok else 400)


@router.get("/google/callback")
async def google_callback(request: Request, session: SessionDep,
                          code: str = "", state: str = "", error: str = ""):
    """Google redirects here. Verify everything, then hand the SPA a token."""
    if error:
        return _closing_page(f"Google reported: {error}", ok=False)
    if not _google_enabled():
        return _closing_page("Google sign-in is not configured on this server.", ok=False)

    _sweep()
    pending = _pending.pop(state, None)   # single use - replay is rejected
    if pending is None:
        return _closing_page(
            "This sign-in link has expired or was already used. Please try again.",
            ok=False)
    if not code:
        return _closing_page("Google did not return an authorization code.", ok=False)

    try:
        tokens = await google_oauth.exchange_code(
            code=code, client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            redirect_uri=pending.redirect_uri, code_verifier=pending.verifier)
        claims = await google_oauth.verify_id_token(
            tokens["id_token"], client_id=settings.google_client_id,
            nonce=pending.nonce, allowed_domains=_allowed_domains())
    except OAuthError as exc:
        return _closing_page(str(exc), ok=False)

    user = _upsert_google_user(session, claims)
    if not user.is_active:
        return _closing_page("This account is disabled.", ok=False)

    issued = _token_for(user)
    # Hand the token to the SPA through the URL fragment: fragments are not sent
    # to the server and do not appear in access logs or Referer headers. The
    # login page reads it, stores it, and immediately clears the hash.
    fragment = urlencode({"token": issued.access_token,
                          "next": pending.next_path}, quote_via=quote)
    return RedirectResponse(f"{_base_url(request)}/login#{fragment}",
                            status_code=status.HTTP_303_SEE_OTHER)


def _upsert_google_user(session, claims: dict) -> User:
    """Find or create the local account for a verified Google identity.

    Matched on the Google subject id first: `sub` is stable and unique, whereas
    an email address can be reassigned within a workspace. Falling back to email
    links an existing password account to Google on first SSO sign-in.
    """
    sub = claims.get("sub") or ""
    email = claims["email"]

    user = None
    if sub:
        user = session.exec(select(User).where(User.google_sub == sub)).first()
    if user is None:
        user = session.exec(select(User).where(User.email == email)).first()

    if user is None:
        # New accounts get the lowest useful role. Promotion is deliberate,
        # never inferred from an email address.
        user = User(
            email=email,
            full_name=claims.get("name") or email.split("@")[0],
            role=Role.INTERN,
            google_sub=sub or None,
            avatar_url=claims.get("picture") or "",
            # No usable password: this account signs in through Google. A random
            # secret means the password path can never match.
            hashed_password=hash_password(secrets.token_urlsafe(32)),
        )
        session.add(user)
    else:
        if sub and not user.google_sub:
            user.google_sub = sub
        if claims.get("picture") and not user.avatar_url:
            user.avatar_url = claims["picture"]
        if claims.get("name") and not user.full_name:
            user.full_name = claims["name"]
        session.add(user)

    session.commit()
    session.refresh(user)
    return user


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut(id=user.id or 0, email=user.email, full_name=user.full_name,
                   role=user.role, cohort=user.cohort, avatar_url=user.avatar_url)


@router.get("/demo-accounts")
def demo_accounts() -> list[dict]:
    """
    Seeded demo credentials, for development convenience only.

    This hands out plaintext passwords to unauthenticated callers, so it is
    disabled outside development - otherwise a production deployment would
    publish working logins to anyone who found the URL.
    """
    if settings.is_production:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    # Derived from the seed list so the two can never drift apart.
    from app.services.seed import USERS

    return [
        {"email": email, "password": password, "role": role.value.lower(), "name": name}
        for email, name, role, password, _cohort in USERS
    ]
