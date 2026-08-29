"""Google OAuth 2.0 - Authorization Code flow with PKCE.

Why the authorization-code flow and not the simpler implicit/one-tap style: the
browser never handles a long-lived credential, the code is exchanged
server-side using the client secret, and the resulting id_token is verified
against Google's published keys before we trust a single claim in it.

Verification is done locally against Google's JWKS rather than by calling the
`tokeninfo` endpoint per login. That endpoint is rate-limited, adds a network
round trip to every sign-in, and is documented as a debugging aid. Verifying the
RS256 signature ourselves is the supported production path.

Only the standard library plus httpx is used, so this adds no dependency.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

# Small clock-skew allowance so a slightly fast/slow server does not reject
# otherwise valid tokens.
LEEWAY_SECONDS = 120


class OAuthError(Exception):
    """Raised for any failure that should abort the sign-in."""


# --------------------------------------------------------------------------
# base64url helpers - JWTs use the unpadded URL-safe alphabet
# --------------------------------------------------------------------------
def _b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


# --------------------------------------------------------------------------
# PKCE
# --------------------------------------------------------------------------
def make_pkce_pair() -> tuple[str, str]:
    """Return (verifier, challenge) for PKCE S256.

    PKCE stops an attacker who intercepts the redirect (a malicious app
    registered on the same custom scheme, a shared machine, a leaky proxy log)
    from redeeming the authorization code: the token exchange requires the
    verifier, which never left the server.
    """
    verifier = _b64url_encode(secrets.token_bytes(64))
    challenge = _b64url_encode(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def build_authorize_url(*, client_id: str, redirect_uri: str, state: str,
                        code_challenge: str, nonce: str,
                        login_hint: str = "") -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        # Always show the chooser: on a shared machine, silently reusing the
        # last Google session is a footgun.
        "prompt": "select_account",
        "access_type": "online",
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


# --------------------------------------------------------------------------
# JWKS
# --------------------------------------------------------------------------
@dataclass
class _JwksCache:
    keys: dict[str, dict[str, Any]]
    fetched_at: float


_jwks_cache: _JwksCache | None = None
_JWKS_TTL = 3600.0


async def _get_jwks(force: bool = False) -> dict[str, dict[str, Any]]:
    """Google's signing keys, cached for an hour.

    Keys rotate, so a cache miss on an unknown `kid` triggers one forced
    refetch before giving up.
    """
    global _jwks_cache
    fresh = (_jwks_cache is not None
             and time.time() - _jwks_cache.fetched_at < _JWKS_TTL)
    if fresh and not force:
        assert _jwks_cache is not None
        return _jwks_cache.keys

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(JWKS_URI)
        resp.raise_for_status()
        keys = {k["kid"]: k for k in resp.json().get("keys", []) if "kid" in k}
    except Exception as exc:  # network, DNS, malformed payload
        if _jwks_cache is not None:
            # Serve stale keys rather than locking everyone out over a blip.
            return _jwks_cache.keys
        raise OAuthError(f"Could not fetch Google signing keys: {exc}") from exc

    if not keys:
        raise OAuthError("Google returned an empty key set")
    _jwks_cache = _JwksCache(keys=keys, fetched_at=time.time())
    return keys


def _verify_rs256(signing_input: bytes, signature: bytes,
                  jwk: dict[str, Any]) -> bool:
    """Verify an RS256 signature using PKCS#1 v1.5, implemented on integers.

    Avoids adding a crypto dependency for what is a modular exponentiation and
    a constant-time compare against a DigestInfo-prefixed SHA-256 hash.
    """
    n = int.from_bytes(_b64url_decode(jwk["n"]), "big")
    e = int.from_bytes(_b64url_decode(jwk["e"]), "big")
    sig_int = int.from_bytes(signature, "big")
    if sig_int >= n:
        return False

    k = (n.bit_length() + 7) // 8
    if len(signature) != k:
        return False

    em = pow(sig_int, e, n).to_bytes(k, "big")

    # RFC 8017 EMSA-PKCS1-v1_5: 0x00 0x01 PS 0x00 DigestInfo
    sha256_digestinfo = bytes.fromhex("3031300d060960864801650304020105000420")
    expected = (b"\x00\x01"
                + b"\xff" * (k - len(sha256_digestinfo) - 32 - 3)
                + b"\x00"
                + sha256_digestinfo
                + hashlib.sha256(signing_input).digest())
    return secrets.compare_digest(em, expected)


# --------------------------------------------------------------------------
# id_token verification
# --------------------------------------------------------------------------
async def verify_id_token(id_token: str, *, client_id: str,
                          nonce: str | None = None,
                          allowed_domains: set[str] | None = None,
                          _retry: bool = True) -> dict[str, Any]:
    """Validate a Google id_token and return its claims.

    Checks, in order: structure, algorithm, signature, issuer, audience,
    expiry, email presence, email_verified, and optionally the hosted domain.
    Any failure raises OAuthError - callers must not fall back to trusting
    unverified input.
    """
    parts = id_token.split(".")
    if len(parts) != 3:
        raise OAuthError("Malformed id_token")

    try:
        header = json.loads(_b64url_decode(parts[0]))
        claims = json.loads(_b64url_decode(parts[1]))
        signature = _b64url_decode(parts[2])
    except Exception as exc:
        raise OAuthError("Could not decode id_token") from exc

    # Reject "alg": "none" and any algorithm we do not actually verify -
    # accepting the header's word for it is the classic JWT bypass.
    if header.get("alg") != "RS256":
        raise OAuthError(f"Unexpected token algorithm: {header.get('alg')!r}")

    kid = header.get("kid")
    if not kid:
        raise OAuthError("id_token has no key id")

    keys = await _get_jwks()
    jwk = keys.get(kid)
    if jwk is None and _retry:
        keys = await _get_jwks(force=True)   # keys may have just rotated
        jwk = keys.get(kid)
    if jwk is None:
        raise OAuthError("id_token signed with an unknown key")

    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
    if not _verify_rs256(signing_input, signature, jwk):
        raise OAuthError("id_token signature is not valid")

    if claims.get("iss") not in ISSUERS:
        raise OAuthError(f"Unexpected issuer: {claims.get('iss')!r}")

    # The audience check is what stops a valid Google token minted for a
    # *different* application from logging someone in here.
    if not client_id:
        raise OAuthError("Server has no Google client id configured")
    aud = claims.get("aud")
    if aud != client_id:
        raise OAuthError("id_token was issued for a different application")

    now = time.time()
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)) or now > exp + LEEWAY_SECONDS:
        raise OAuthError("id_token has expired")
    iat = claims.get("iat")
    if isinstance(iat, (int, float)) and iat > now + LEEWAY_SECONDS:
        raise OAuthError("id_token was issued in the future")

    if nonce is not None and claims.get("nonce") != nonce:
        raise OAuthError("id_token nonce does not match this sign-in attempt")

    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise OAuthError("Google account has no email address")

    # email_verified can arrive as a bool or the string "true".
    verified = claims.get("email_verified")
    if verified not in (True, "true"):
        raise OAuthError("Google account email is not verified")

    if allowed_domains:
        domain = (claims.get("hd") or email.rsplit("@", 1)[-1]).lower()
        if domain not in allowed_domains:
            raise OAuthError(f"Sign-in is restricted; {domain} is not allowed")

    claims["email"] = email
    return claims


async def exchange_code(*, code: str, client_id: str, client_secret: str,
                        redirect_uri: str, code_verifier: str) -> dict[str, Any]:
    """Swap an authorization code for tokens. Requires the PKCE verifier."""
    data = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": code_verifier,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(TOKEN_ENDPOINT, data=data)
    except Exception as exc:
        raise OAuthError(f"Could not reach Google: {exc}") from exc

    if resp.status_code != 200:
        detail = ""
        try:
            detail = resp.json().get("error_description") or resp.json().get("error", "")
        except Exception:
            detail = resp.text[:200]
        raise OAuthError(f"Google rejected the authorization code: {detail}")

    payload = resp.json()
    if "id_token" not in payload:
        raise OAuthError("Google response contained no id_token")
    return payload
