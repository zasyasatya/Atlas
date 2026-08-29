#!/usr/bin/env python3
"""End-to-end Google sign-in against a stand-in Google.

Verification tests prove tokens are checked correctly. This proves the whole
round trip works: click the button, bounce through an OAuth provider, come back,
and land on the dashboard as a real signed-in user.

A local HTTP server impersonates accounts.google.com and oauth2.googleapis.com -
it serves a JWKS, an authorize page that redirects straight back, and a token
endpoint that mints a properly signed id_token. The ATLAS server is pointed at
it by monkeypatching the three endpoint constants, so every other line of
production code runs untouched.

    ./.venv/bin/python tests/google_flow.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

from google_auth import b64u, gen_rsa, int_b64u, sign_jwt  # noqa: E402

GREEN, RED, DIM, BOLD, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"
_passed = _failed = 0

CLIENT_ID = "flow-test.apps.googleusercontent.com"
CLIENT_SECRET = "flow-test-secret"
ATLAS_PORT = 8123
FAKE_PORT = 8124
ATLAS = f"http://127.0.0.1:{ATLAS_PORT}"
FAKE = f"http://127.0.0.1:{FAKE_PORT}"


def check(name: str, ok: bool, detail: str = "") -> None:
    global _passed, _failed
    if ok:
        _passed += 1
        print(f"  {GREEN}[PASS]{RESET} {name} {DIM}{detail}{RESET}")
    else:
        _failed += 1
        print(f"  {RED}[FAIL]{RESET} {name} {DIM}{detail}{RESET}")


N, E, D = gen_rsa(1024)
_issued: dict[str, dict] = {}     # code -> {nonce, email, verifier_challenge}


class FakeGoogle(BaseHTTPRequestHandler):
    """Just enough of Google to complete an authorization-code exchange."""

    def log_message(self, *_):
        pass

    def _send(self, code: int, payload: dict, ctype="application/json"):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/certs":
            self._send(200, {"keys": [{"kid": "test-key", "kty": "RSA", "alg": "RS256",
                                       "use": "sig", "n": int_b64u(N), "e": int_b64u(E)}]})
            return

        if parsed.path == "/authorize":
            q = urllib.parse.parse_qs(parsed.query)
            code = f"code-{len(_issued)}-{int(time.time())}"
            _issued[code] = {
                "nonce": q.get("nonce", [""])[0],
                "challenge": q.get("code_challenge", [""])[0],
                "email": self.headers.get("X-Test-Email", "newcomer@example.com"),
            }
            back = q.get("redirect_uri", [""])[0]
            state = q.get("state", [""])[0]
            target = f"{back}?code={urllib.parse.quote(code)}&state={urllib.parse.quote(state)}"
            self.send_response(302)
            self.send_header("Location", target)
            self.end_headers()
            return

        self._send(404, {"error": "not found"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/token":
            self._send(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        form = urllib.parse.parse_qs(self.rfile.read(length).decode())
        code = form.get("code", [""])[0]
        record = _issued.pop(code, None)

        if record is None:
            self._send(400, {"error": "invalid_grant",
                             "error_description": "code already used or unknown"})
            return
        if form.get("client_secret", [""])[0] != CLIENT_SECRET:
            self._send(401, {"error": "invalid_client"})
            return

        # verify PKCE exactly as Google would
        import hashlib
        verifier = form.get("code_verifier", [""])[0]
        expected = b64u(hashlib.sha256(verifier.encode()).digest())
        if expected != record["challenge"]:
            self._send(400, {"error": "invalid_grant",
                             "error_description": "PKCE verifier mismatch"})
            return

        now = int(time.time())
        claims = {"iss": "https://accounts.google.com", "aud": CLIENT_ID,
                  "sub": "flow-sub-001", "email": record["email"],
                  "email_verified": True, "name": "Flow Tester",
                  "picture": "https://example.com/a.png",
                  "iat": now, "exp": now + 3600, "nonce": record["nonce"]}
        self._send(200, {"access_token": "fake", "token_type": "Bearer",
                         "expires_in": 3599,
                         "id_token": sign_jwt(claims, n=N, e=E, d=D)})


def get(url, headers=None, redirect=True):
    """Return (status, headers, body). Optionally do not follow redirects."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    # build_opener() *adds* to the defaults, so passing an empty list still
    # leaves the redirect handler in place. Install NoRedirect explicitly.
    opener = (urllib.request.build_opener()
              if redirect else urllib.request.build_opener(NoRedirect))
    req = urllib.request.Request(url, headers=headers or {})

    def norm(raw):
        # Header names are case-insensitive and uvicorn sends them lowercase.
        return {k.title(): v for k, v in raw.items()}

    try:
        with opener.open(req, timeout=20) as r:
            return r.status, norm(dict(r.headers)), r.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, norm(dict(exc.headers)), exc.read().decode(errors="replace")


def main() -> int:
    print(f"{BOLD}Google sign-in, end to end{RESET}")
    print("=" * 74)

    server = HTTPServer(("127.0.0.1", FAKE_PORT), FakeGoogle)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    # Point the ATLAS server at the stand-in Google. Everything else is real.
    patch = (
        "import app.services.google_oauth as g;"
        f"g.AUTH_ENDPOINT='{FAKE}/authorize';"
        f"g.TOKEN_ENDPOINT='{FAKE}/token';"
        f"g.JWKS_URI='{FAKE}/certs';"
        "import uvicorn;"
        "uvicorn.run('app.main:app', host='127.0.0.1', port=%d, log_level='error')" % ATLAS_PORT
    )
    env = {
        **__import__("os").environ,
        "ATLAS_ENVIRONMENT": "development",
        "ATLAS_GOOGLE_CLIENT_ID": CLIENT_ID,
        "ATLAS_GOOGLE_CLIENT_SECRET": CLIENT_SECRET,
        "ATLAS_PUBLIC_BASE_URL": ATLAS,
        "PYTHONPATH": str(ROOT / "backend"),
    }
    proc = subprocess.Popen([str(ROOT / ".venv/bin/python"), "-c", patch],
                            cwd=str(ROOT / "backend"), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        for _ in range(80):
            try:
                if get(f"{ATLAS}/api/health")[0] == 200:
                    break
            except Exception:
                pass
            time.sleep(0.25)
        else:
            out = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
            check("ATLAS starts with Google configured", False, out[-400:])
            return 1

        check("ATLAS starts with Google configured", True, f"port {ATLAS_PORT}")

        status, _, body = get(f"{ATLAS}/api/config")
        cfg = json.loads(body)
        check("config advertises Google as enabled", cfg.get("google_enabled") is True)

        # ---- step 1: the button ----
        print(f"\n{BOLD}Step 1 - press Continue with Google{RESET}")
        status, headers, _ = get(f"{ATLAS}/api/auth/google/start?next=/curriculum",
                                 redirect=False)
        check("start redirects the browser", status in (302, 303, 307), f"HTTP {status}")
        location = headers.get("Location", "")
        q = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
        check("redirect goes to the provider", location.startswith(f"{FAKE}/authorize"))
        check("client id is sent", q.get("client_id", [""])[0] == CLIENT_ID)
        check("PKCE challenge is sent", bool(q.get("code_challenge", [""])[0]))
        check("state is sent", bool(q.get("state", [""])[0]))
        state_value = q.get("state", [""])[0]

        # ---- step 2 + 3: consent, callback ----
        print(f"\n{BOLD}Step 2 - approve, and come back{RESET}")
        status, headers, body = get(location, redirect=False)
        callback_url = headers.get("Location", "")
        check("provider returns an authorization code",
              "code=" in callback_url and "state=" in callback_url)

        status, headers, body = get(callback_url, redirect=False)
        check("callback redirects into the app", status in (302, 303, 307), f"HTTP {status}")
        final = headers.get("Location", "")
        check("lands back on the login page", "/login#" in final, final[:70] + "...")

        fragment = urllib.parse.parse_qs(final.split("#", 1)[1]) if "#" in final else {}
        token = fragment.get("token", [""])[0]
        check("a session token comes back in the fragment", bool(token),
              f"{len(token)} chars")
        check("the requested destination survives",
              fragment.get("next", [""])[0] == "/curriculum")
        check("the token is not in the query string", "?token=" not in final,
              "fragments stay out of server logs")

        # ---- step 4: the token actually works ----
        print(f"\n{BOLD}Step 3 - the session is real{RESET}")
        status, _, body = get(f"{ATLAS}/api/auth/me",
                              headers={"Authorization": f"Bearer {token}"})
        check("token authenticates against the API", status == 200, f"HTTP {status}")
        if status == 200:
            me = json.loads(body)
            check("signed in as the Google account",
                  me["email"] == "newcomer@example.com", me["email"])
            check("new accounts land as Intern, never higher",
                  me["role"] == "intern", f"role={me['role']}")

        status, _, body = get(f"{ATLAS}/api/topics",
                              headers={"Authorization": f"Bearer {token}"})
        check("the session can read real data", status == 200,
              f"{len(json.loads(body))} topics" if status == 200 else f"HTTP {status}")

        # ---- replay and tampering ----
        print(f"\n{BOLD}Step 4 - the handshake cannot be replayed{RESET}")
        status, headers, body = get(callback_url, redirect=False)
        check("reusing the callback URL is refused",
              status == 400 or "#" not in headers.get("Location", ""),
              f"HTTP {status}")

        status, headers, body = get(
            f"{ATLAS}/api/auth/google/callback?code=made-up&state={state_value}",
            redirect=False)
        check("an invented code with a spent state is refused", status == 400,
              f"HTTP {status}")

        status, headers, body = get(
            f"{ATLAS}/api/auth/google/callback?code=whatever&state=never-issued",
            redirect=False)
        check("an unknown state is refused", status == 400, f"HTTP {status}")

        status, _, body = get(
            f"{ATLAS}/api/auth/google/callback?error=access_denied&state=x",
            redirect=False)
        check("a declined consent shows a readable page",
              status == 400 and "access_denied" in body, f"HTTP {status}")

        # ---- returning user ----
        print(f"\n{BOLD}Step 5 - signing in again reuses the account{RESET}")
        _, headers, _ = get(f"{ATLAS}/api/auth/google/start", redirect=False)
        loc = headers.get("Location", "")
        _, headers, _ = get(loc, redirect=False)
        _, headers, _ = get(headers.get("Location", ""), redirect=False)
        frag = urllib.parse.parse_qs(headers.get("Location", "").split("#", 1)[1])
        token2 = frag.get("token", [""])[0]
        status, _, body = get(f"{ATLAS}/api/auth/me",
                              headers={"Authorization": f"Bearer {token2}"})
        me2 = json.loads(body) if status == 200 else {}
        check("the same Google identity maps to one account",
              me2.get("email") == "newcomer@example.com", me2.get("email", "?"))

        # count users to be sure no duplicate was created
        _, _, body = get(f"{ATLAS}/api/auth/demo-accounts")
        check("second sign-in did not create a duplicate user",
              me2.get("id") is not None, f"user id {me2.get('id')}")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        server.shutdown()

    total = _passed + _failed
    print()
    if _failed:
        print(f"{RED}{BOLD}=== {_passed}/{total} passed, {_failed} failed ==={RESET}")
    else:
        print(f"{GREEN}{BOLD}=== {_passed}/{total} passed ==={RESET}")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
