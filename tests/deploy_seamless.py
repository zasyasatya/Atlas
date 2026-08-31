#!/usr/bin/env python
"""The one claim this platform makes, tested end to end: deploy, then open it.

Everything else in the suite is a unit or a rendered file. This starts a real
uvicorn process, logs in, uploads a real bundle, runs the real deploy pipeline
(venv, requirements, health wait), and then asks the *portal's own port* for the
app's virtual directory - which is the request that used to fail quietly while the
database cheerfully reported "running".

    python tests/deploy_seamless.py

Needs no nginx, no streamlit, no public URL and no network: the probe app is
stdlib-only, and it is launched exactly the way a cohort's real app is.
"""
from __future__ import annotations

import io
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

_results: list[tuple[bool, str]] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    _results.append((ok, name))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' - ' + extra) if extra and not ok else ''}",
          flush=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# A deployed app, as an intern would ship one: bind the port you were given, serve
# under the base path you were given. "gradio" appears in requirements.txt so the
# scaffold does not decide it must add the framework to a probe that needs none.
APP_SOURCE = '''
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ.get("GRADIO_SERVER_PORT") or "8600")
BASE = (os.environ.get("GRADIO_ROOT_PATH") or "").strip("/")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = "ATLAS-APP-OK base=/{base} path={path}".format(base=BASE, path=self.path).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
'''
REQUIREMENTS = "# gradio is not needed by this probe; stdlib http.server only\n"


def bundle_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("app.py", APP_SOURCE.strip() + "\n")
        zf.writestr("requirements.txt", REQUIREMENTS)
    return buf.getvalue()


def wait_for_url(client, url: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if client.get(url).status_code < 500:
                return True
        except Exception:  # noqa: BLE001 - not listening yet is the expected case
            pass
        time.sleep(0.4)
    return False


def main() -> int:
    try:
        import httpx
    except ImportError:
        print("SKIP: this test needs httpx (pip install httpx)")
        return 0
    if shutil.which(sys.executable) is None:
        print("SKIP: the deploy runner needs a real interpreter on PATH")
        return 0

    storage = Path(tempfile.mkdtemp(prefix="atlas-seamless-"))
    port = free_port()
    lo, hi = free_port(), 0
    hi = lo + 4
    env = dict(
        os.environ,
        PYTHONPATH=str(ROOT / "backend"),
        ATLAS_STORAGE_DIR=str(storage),
        ATLAS_SEED_DEMO_DATA="true",
        ATLAS_ENVIRONMENT="development",
        ATLAS_SECRET_KEY="seamless-test-key-not-a-secret",
        ATLAS_PUBLIC_BASE_URL="",
        ATLAS_DEPLOY_DRIVER="local_process",
        ATLAS_DEPLOY_BUILTIN_PROXY="true",
        ATLAS_DEPLOY_PORT_START=str(lo),
        ATLAS_DEPLOY_PORT_END=str(hi),
        ATLAS_NGINX_AUTO_INSTALL="false",
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(timeout=httpx.Timeout(300.0, connect=3.0)) as client:
            print("server:")
            started = wait_for_url(client, f"{base}/api/health", 60)
            check("the platform boots", started)
            if not started:
                raise SystemExit(_dump(proc))

            creds = client.get(f"{base}/api/auth/demo-accounts").json()
            admin = next((c for c in creds if c["role"] == "admin"), creds[0])
            token = client.post(f"{base}/api/auth/login", json={
                "email": admin["email"], "password": admin["password"]}).json()["access_token"]
            auth = {"Authorization": f"Bearer {token}"}
            topic_id = client.get(f"{base}/api/topics", headers=auth).json()[0]["id"]

            dep = client.post(f"{base}/api/deployments", headers=auth, json={
                "name": "Seamless Check", "topic_id": topic_id,
                "framework": "gradio", "entrypoint": "app.py"}).json()
            slug = dep["slug"]

            print("deploy:")
            files = {"file": ("bundle.zip", bundle_zip(), "application/zip")}
            uploaded = client.post(f"{base}/api/deployments/{dep['id']}/bundle",
                                   headers=auth, files=files)
            check("the bundle is accepted", uploaded.status_code == 200,
                  uploaded.text[:200])

            t0 = time.monotonic()
            deployed = client.post(f"{base}/api/deployments/{dep['id']}/deploy", headers=auth)
            body = deployed.json() if deployed.status_code == 200 else {}
            check("deploy reports the app as running",
                  body.get("status") == "running",
                  f"status={body.get('status')} logs={str(body.get('build_logs'))[-400:]}")
            print(f"      (deploy took {time.monotonic() - t0:.1f}s)")

            print("the promise:")
            check("the published URL is a virtual directory on the portal's own origin",
                  body.get("url") == f"/app/{slug}/", f"url={body.get('url')!r}")

            direct = client.get(f"{base}/app/{slug}/hello")
            check("GET /app/<slug>/ on the portal port reaches the app",
                  direct.status_code == 200 and "ATLAS-APP-OK" in direct.text,
                  f"{direct.status_code}: {direct.text[:160]}")
            check("the app was launched with the virtual directory as its base path",
                  f"base=/app/{slug}" in direct.text and "path=/app/" in direct.text,
                  direct.text[:200])
            check("the app saw the path it was mounted at, not a stripped one",
                  f"path=/app/{slug}/hello" in direct.text, direct.text[:200])

            bare = client.get(f"{base}/app/{slug}", follow_redirects=False)
            check("the bare path redirects to the trailing-slash form",
                  bare.status_code == 307 and bare.headers.get("location") == f"/app/{slug}/")

            stat = client.get(f"{base}/api/deployments/proxy-status", headers=auth).json()
            check("routing status says the app is served by ATLAS itself",
                  stat["builtin"]["enabled"] is True and "atlas" in stat["serving_mode"],
                  str(stat.get("serving_mode")))
            check("and it probes the app as live, not just recorded as running",
                  stat["live"] == 1 and stat["expected"] == 1, str(stat.get("checks")))

            vhost = client.get(f"{base}/api/deployments/proxy-config", headers=auth).text
            check("the optional nginx block for this app is still generated",
                  f"location ^~ /app/{slug}/" in vhost)

            print("stopping:")
            stopped = client.post(f"{base}/api/deployments/{dep['id']}/stop", headers=auth)
            check("stop is accepted", stopped.status_code == 200)
            gone = client.get(f"{base}/app/{slug}/hello")
            check("after a stop the path explains the app is stopped instead of 500-ing",
                  gone.status_code == 200 and "stopped" in gone.text.lower(),
                  f"{gone.status_code}")

            deleted = client.delete(f"{base}/api/deployments/{dep['id']}", headers=auth)
            check("delete cleans up without leaving a route behind",
                  deleted.status_code == 204
                  and client.get(f"{base}/api/deployments/proxy-config", headers=auth)
                  .status_code == 200)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - never leave a server running on failure
        check(f"the run completed ({type(exc).__name__}: {exc})", False)
        print(_dump(proc))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        for _ in range(20):  # the deployed app is a child of the platform, by design
            try:
                shutil.rmtree(storage)
                break
            except OSError:
                time.sleep(0.5)

    failed = [n for ok, n in _results if not ok]
    print(f"\n{len(_results) - len(failed)}/{len(_results)} checks passed")
    if failed:
        print("FAILED:")
        for n in failed:
            print("  -", n)
        return 1
    print("ALL SEAMLESS-DEPLOY CHECKS PASSED")
    return 0


def _dump(proc: subprocess.Popen) -> str:
    try:
        proc.terminate()
        out, _ = proc.communicate(timeout=10)
    except Exception:  # noqa: BLE001
        out = ""
    return "\n--- server output ---\n" + (out or "")[-3000:]


if __name__ == "__main__":
    raise SystemExit(main())
