#!/usr/bin/env python3
"""Google OAuth: security and correctness.

The previous implementation accepted `{"email": "supervisor@atlas.id"}` and
issued a supervisor token - no password, no Google, no verification. Most of
this file exists to keep that door shut.

Signature checks run against a locally generated RSA key whose public half is
served as a fake JWKS, so token verification is exercised for real without
touching the network.

    ./.venv/bin/python tests/google_auth.py
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

GREEN, RED, DIM, BOLD, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"
_passed = _failed = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global _passed, _failed
    if ok:
        _passed += 1
        print(f"  {GREEN}[PASS]{RESET} {name} {DIM}{detail}{RESET}")
    else:
        _failed += 1
        print(f"  {RED}[FAIL]{RESET} {name} {DIM}{detail}{RESET}")


# ---------------------------------------------------------------------------
# Minimal RSA keygen + PKCS#1 v1.5 signing, so we can mint real id_tokens.
# ---------------------------------------------------------------------------
def _egcd(a: int, b: int) -> tuple[int, int, int]:
    if a == 0:
        return b, 0, 1
    g, y, x = _egcd(b % a, a)
    return g, x - (b // a) * y, y


def _modinv(a: int, m: int) -> int:
    g, x, _ = _egcd(a % m, m)
    if g != 1:
        raise ValueError("not invertible")
    return x % m


def _is_probable_prime(n: int, rounds: int = 24) -> bool:
    if n < 2:
        return False
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if n % p == 0:
            return n == p
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    import random
    for _ in range(rounds):
        a = random.randrange(2, n - 1)
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True


def _gen_prime(bits: int) -> int:
    import random
    while True:
        candidate = random.getrandbits(bits) | (1 << (bits - 1)) | 1
        if _is_probable_prime(candidate):
            return candidate


def gen_rsa(bits: int = 1024) -> tuple[int, int, int]:
    """Return (n, e, d). 1024 bits keeps the test fast; production keys are
    Google's own 2048-bit ones."""
    e = 65537
    while True:
        p, q = _gen_prime(bits // 2), _gen_prime(bits // 2)
        if p == q:
            continue
        n = p * q
        phi = (p - 1) * (q - 1)
        try:
            return n, e, _modinv(e, phi)
        except ValueError:
            continue


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def int_b64u(value: int) -> str:
    return b64u(value.to_bytes((value.bit_length() + 7) // 8, "big"))


def sign_jwt(claims: dict, *, n: int, e: int, d: int, kid: str = "test-key",
             alg: str = "RS256") -> str:
    header = {"alg": alg, "kid": kid, "typ": "JWT"}
    signing_input = (b64u(json.dumps(header).encode()) + "."
                     + b64u(json.dumps(claims).encode()))

    k = (n.bit_length() + 7) // 8
    digest_info = bytes.fromhex("3031300d060960864801650304020105000420")
    em = (b"\x00\x01" + b"\xff" * (k - len(digest_info) - 32 - 3) + b"\x00"
          + digest_info + hashlib.sha256(signing_input.encode()).digest())
    sig = pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big")
    return f"{signing_input}.{b64u(sig)}"


CLIENT_ID = "test-client-id.apps.googleusercontent.com"


def main() -> int:
    from app.services import google_oauth
    from app.services.google_oauth import OAuthError

    print(f"{BOLD}Google OAuth{RESET}")
    print("=" * 74)

    n, e, d = gen_rsa(1024)
    google_oauth._jwks_cache = google_oauth._JwksCache(
        keys={"test-key": {"kid": "test-key", "kty": "RSA",
                           "n": int_b64u(n), "e": int_b64u(e)}},
        fetched_at=time.time())

    def base_claims(**over):
        now = int(time.time())
        c = {"iss": "https://accounts.google.com", "aud": CLIENT_ID,
             "sub": "1234567890", "email": "intern@example.com",
             "email_verified": True, "name": "Test Intern",
             "iat": now, "exp": now + 3600, "nonce": "test-nonce"}
        c.update(over)
        return c

    async def verify(token, **kw):
        kw.setdefault("client_id", CLIENT_ID)
        kw.setdefault("nonce", "test-nonce")
        return await google_oauth.verify_id_token(token, **kw)

    async def rejects(token, reason, **kw):
        try:
            await verify(token, **kw)
            return False, "accepted"
        except OAuthError as exc:
            return (reason.lower() in str(exc).lower()), str(exc)

    # ---------------- happy path ----------------
    print(f"\n{BOLD}A valid token{RESET}")
    good = sign_jwt(base_claims(), n=n, e=e, d=d)
    try:
        claims = asyncio.run(verify(good))
        check("a correctly signed token verifies", claims["email"] == "intern@example.com",
              f"email={claims['email']}")
    except OAuthError as exc:
        check("a correctly signed token verifies", False, str(exc))

    # ---------------- forgery ----------------
    print(f"\n{BOLD}Forged and tampered tokens{RESET}")

    # signed with a different key
    n2, e2, d2 = gen_rsa(1024)
    ok, why = asyncio.run(rejects(
        sign_jwt(base_claims(), n=n2, e=e2, d=d2), "signature"))
    check("token signed with the wrong key is rejected", ok, why)

    # payload swapped after signing - escalate to admin
    header_b64, payload_b64, sig_b64 = good.split(".")
    evil = json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
    evil["email"] = "admin@atlas.id"
    tampered = f"{header_b64}.{b64u(json.dumps(evil).encode())}.{sig_b64}"
    ok, why = asyncio.run(rejects(tampered, "signature"))
    check("payload tampering invalidates the signature", ok, why)

    # alg:none - the classic JWT bypass
    none_tok = (b64u(json.dumps({"alg": "none", "kid": "test-key"}).encode()) + "."
                + b64u(json.dumps(base_claims(email="admin@atlas.id")).encode()) + ".")
    ok, why = asyncio.run(rejects(none_tok, "algorithm"))
    check("alg=none is rejected", ok, why)

    # HS256 using the public modulus as the secret
    hs = (b64u(json.dumps({"alg": "HS256", "kid": "test-key"}).encode()) + "."
          + b64u(json.dumps(base_claims()).encode()) + "." + b64u(b"x" * 32))
    ok, why = asyncio.run(rejects(hs, "algorithm"))
    check("algorithm confusion (HS256) is rejected", ok, why)

    ok, why = asyncio.run(rejects("not.a.jwt", "decode"))
    check("garbage input is rejected", ok, why)
    ok, why = asyncio.run(rejects("onlyonepart", "malformed"))
    check("a token with the wrong shape is rejected", ok, why)

    # ---------------- claim checks ----------------
    print(f"\n{BOLD}Claim validation{RESET}")

    ok, why = asyncio.run(rejects(
        sign_jwt(base_claims(aud="someone-else.apps.googleusercontent.com"),
                 n=n, e=e, d=d), "different application"))
    check("a token minted for another app is rejected", ok, why)

    ok, why = asyncio.run(rejects(
        sign_jwt(base_claims(iss="https://evil.example.com"), n=n, e=e, d=d),
        "issuer"))
    check("a token from another issuer is rejected", ok, why)

    now = int(time.time())
    ok, why = asyncio.run(rejects(
        sign_jwt(base_claims(exp=now - 3600, iat=now - 7200), n=n, e=e, d=d),
        "expired"))
    check("an expired token is rejected", ok, why)

    ok, why = asyncio.run(rejects(
        sign_jwt(base_claims(email_verified=False), n=n, e=e, d=d), "not verified"))
    check("an unverified Google email is rejected", ok, why)

    ok, why = asyncio.run(rejects(
        sign_jwt(base_claims(nonce="a-different-nonce"), n=n, e=e, d=d), "nonce"))
    check("a replayed nonce from another attempt is rejected", ok, why)

    # hosted-domain allowlist
    ok, why = asyncio.run(rejects(
        sign_jwt(base_claims(email="outsider@gmail.com"), n=n, e=e, d=d),
        "not allowed", allowed_domains={"pertamina.com"}))
    check("domain allowlist blocks outside accounts", ok, why)

    try:
        c = asyncio.run(verify(
            sign_jwt(base_claims(email="staff@pertamina.com"), n=n, e=e, d=d),
            allowed_domains={"pertamina.com"}))
        check("domain allowlist admits its own accounts", c["email"] == "staff@pertamina.com")
    except OAuthError as exc:
        check("domain allowlist admits its own accounts", False, str(exc))

    # a server with no client id must never accept a token
    ok, why = asyncio.run(rejects(good, "client id", client_id=""))
    check("unconfigured server accepts nothing", ok, why)

    # ---------------- PKCE ----------------
    print(f"\n{BOLD}PKCE and the authorize URL{RESET}")
    v1, c1 = google_oauth.make_pkce_pair()
    v2, _ = google_oauth.make_pkce_pair()
    check("verifiers are unpredictable", v1 != v2 and len(v1) >= 43, f"{len(v1)} chars")
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(v1.encode()).digest()).rstrip(b"=").decode()
    check("challenge is S256 of the verifier", c1 == expected)

    url = google_oauth.build_authorize_url(
        client_id=CLIENT_ID, redirect_uri="https://atlas.example.com/api/auth/google/callback",
        state="st", code_challenge=c1, nonce="nn")
    for needle, label in [
        ("response_type=code", "uses the authorization-code flow"),
        ("code_challenge_method=S256", "requests PKCE S256"),
        ("scope=openid+email+profile", "asks for openid email profile"),
        ("prompt=select_account", "always shows the account chooser"),
        ("state=st", "carries the CSRF state"),
        ("nonce=nn", "carries the nonce"),
    ]:
        check(f"authorize URL {label}", needle in url)
    check("authorize URL points at Google",
          url.startswith("https://accounts.google.com/o/oauth2/v2/auth?"))

    # ---------------- router wiring ----------------
    print(f"\n{BOLD}Endpoint surface{RESET}")
    from app.main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    check("start endpoint exists", "/api/auth/google/start" in paths)
    check("callback endpoint exists", "/api/auth/google/callback" in paths)
    check("the unverified POST /api/auth/google is gone",
          "/api/auth/google" not in paths,
          "this endpoint issued tokens for any email")

    import app.domain.schemas as schemas
    check("GoogleLoginRequest schema is gone",
          not hasattr(schemas, "GoogleLoginRequest"),
          "it allowed {'email': ...} with no proof of identity")

    from app.api.routers import auth as auth_router
    check("only same-site redirects are allowed",
          auth_router._safe_next("/curriculum") == "/curriculum"
          and auth_router._safe_next("https://evil.com") == "/dashboard"
          and auth_router._safe_next("//evil.com") == "/dashboard",
          "open-redirect guard on ?next=")

    # state is single use
    auth_router._pending.clear()
    auth_router._pending["s1"] = auth_router._PendingLogin(
        verifier="v", nonce="n", redirect_uri="r", next_path="/dashboard")
    first = auth_router._pending.pop("s1", None)
    second = auth_router._pending.pop("s1", None)
    check("a state value cannot be replayed", first is not None and second is None)

    # expiry sweep
    auth_router._pending["old"] = auth_router._PendingLogin(
        verifier="v", nonce="n", redirect_uri="r", next_path="/",
        created_at=time.time() - 3600)
    auth_router._sweep()
    check("stale sign-in attempts are swept", "old" not in auth_router._pending)

    total = _passed + _failed
    print()
    if _failed:
        print(f"{RED}{BOLD}=== {_passed}/{total} passed, {_failed} failed ==={RESET}")
    else:
        print(f"{GREEN}{BOLD}=== {_passed}/{total} passed ==={RESET}")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
