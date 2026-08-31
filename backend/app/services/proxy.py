"""Automatic reverse-proxy (nginx) management for deployed apps.

Every deployed app is served as a **virtual directory** on the main domain
(``https://<domain>/<prefix>/<slug>/``) rather than on its own public port.
This module keeps nginx in sync with the set of running apps automatically:

* one managed snippet per app is written to ``<conf_dir>/atlas-app-<slug>.conf``
  (inside a dedicated ``apps.d`` directory), each containing only that app's
  ``location`` block;
* a ready-to-use standalone vhost is regenerated which, in addition to the
  ``include`` for those snippets, routes everything else (the portal/UI/API)
  to the ATLAS upstream;
* nginx is validated (``nginx -t``) and gracefully reloaded.

The design never edits an operator's existing nginx configuration and never
disturbs other sites/apps:

* only files named ``atlas-app-*.conf`` and the generated ``atlas.conf`` vhost
  are touched — everything else on the nginx host is left alone;
* the snippet directory is dedicated to ATLAS and re-synced from scratch, so
  stopped/deleted apps have their blocks removed with no leftover references;
* a bad configuration is rolled back before reload, so a broken app can never
  take nginx (and therefore the other apps) down.

On a machine without nginx, the generated files are simply stored under the
persistent storage dir so an operator can copy them in later — the deploy
pipeline never fails because a proxy is absent.
"""
from __future__ import annotations

import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings

# A marker written into every managed file so it is obvious who owns it and so
# stale files from older ATLAS versions can be safely reclaimed.
MANAGED_TAG = "# Managed by ATLAS - do not edit by hand; regenerated on deploy."

# Snippet naming prefix inside the apps.d directory.
SNIPPET_PREFIX = "atlas-app-"
VHOST_NAME = "atlas.conf"


# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #
def conf_dir() -> Path:
    """Directory holding one managed <location> snippet per running app."""
    if settings.nginx_conf_dir:
        return Path(settings.nginx_conf_dir)
    return settings.storage_dir / "nginx" / "apps.d"


def vhost_file() -> Path:
    """Full standalone vhost (portal + every app's virtual directory)."""
    if settings.nginx_vhost_file:
        return Path(settings.nginx_vhost_file)
    return settings.storage_dir / "nginx" / VHOST_NAME


def nginx_available() -> bool:
    """True when an nginx binary is on PATH (or a reload command is configured)."""
    return bool(shutil.which("nginx") or settings.nginx_reload_cmd.strip())


def _reload_command() -> list[str] | None:
    """The command used to reload nginx, or None if nginx is not available."""
    override = settings.nginx_reload_cmd.strip()
    if override:
        return shlex.split(override)
    binary = shutil.which("nginx")
    if binary:
        return [binary, "-s", "reload"]
    return None


# --------------------------------------------------------------------------- #
# config rendering
# --------------------------------------------------------------------------- #
def _location_block(r: dict) -> str:
    """The nginx location block for one app's virtual directory."""
    return (
        f"    # --- ATLAS app: {r['name']} ({r['framework']}) ------------------\n"
        f"    # bare virtual directory 301-redirects to the trailing-slash URL\n"
        f"    location = /{r['path']} {{ return 301 /{r['path']}/; }}\n"
        f"    location ^~ /{r['path']}/ {{\n"
        f"        proxy_pass http://127.0.0.1:{r['port']}/{r['path']}/;\n"
        f"        proxy_http_version 1.1;\n"
        f"        # WebSocket support (Streamlit st.core / Gradio live reload)\n"
        f"        proxy_set_header Upgrade $http_upgrade;\n"
        f"        proxy_set_header Connection $connection_upgrade;\n"
        f"        proxy_set_header Host $host;\n"
        f"        proxy_set_header X-Real-IP $remote_addr;\n"
        f"        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        f"        proxy_set_header X-Forwarded-Proto $scheme;\n"
        f"        proxy_set_header X-Forwarded-Prefix /{r['path']};\n"
        f"        proxy_read_timeout 3600s;\n"
        f"        proxy_send_timeout 3600s;\n"
        f"        proxy_buffering off;\n"
        f"        client_max_body_size 0;\n"
        f"    }}\n"
    )


def app_snippet(r: dict) -> str:
    """A standalone, self-documenting snippet file for a single app."""
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"{MANAGED_TAG}\n"
        f"# App      : {r['name']} ({r['framework']})\n"
        f"# Virtual  : /{r['path']}/  ->  127.0.0.1:{r['port']}\n"
        f"# Generated: {generated}\n"
        f"# This file only contains this app's block; add/remove apps never edits\n"
        f"# other apps. It is included from the ATLAS vhost:\n"
        f"#     include {conf_dir()}/{SNIPPET_PREFIX}*.conf;\n\n"
        f"{_location_block(r)}\n"
    )


def apps_server_section(routes: list[dict]) -> str:
    """All per-app location blocks, as embedded in the generated vhost."""
    if not routes:
        return "    # No running deployments yet - deployed apps appear here.\n"
    return "\n".join(_location_block(r) for r in routes)


def full_vhost(routes: list[dict], *, domain: str | None = None) -> str:
    """A complete, self-contained nginx server block.

    It serves every running app under ``/<prefix>/<slug>/`` AND proxies the
    remaining traffic (portal, UI, /api) to the ATLAS FastAPI upstream, so a
    single server block powers the whole platform on one domain/port.
    """
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    d = conf_dir()
    server_name = domain or "_"
    upstream = settings.nginx_upstream.rstrip("/")

    apps = "\n".join(_location_block(r) for r in routes) if routes else (
        "    # No running deployments yet - each deployed app is added here\n"
        "    # automatically as an /<prefix>/<slug>/ virtual directory.\n"
    )

    return f"""{MANAGED_TAG}
# ATLAS full reverse-proxy configuration.
# Generated: {generated}
#
# WHAT THIS DOES
#   * One server block on one domain/port (80 here; put TLS/443 in front).
#   * Each deployed Streamlit/Gradio app is a VIRTUAL DIRECTORY:
#         /{settings.deploy_url_prefix}/<slug>/  ->  the app's internal port.
#   * Everything else (the portal UI and /api) goes to the ATLAS backend.
#
# INSTALL (one time, nginx on the same host as ATLAS):
#   1. Copy this file to /etc/nginx/sites-available/atlas.conf
#        sudo cp {vhost_file()} /etc/nginx/sites-available/atlas.conf
#   2. Enable it:
#        sudo ln -s /etc/nginx/sites-available/atlas.conf /etc/nginx/sites-enabled/
#   3. The map directive below is already included in this file (http context).
#   4. Validate + reload:  sudo nginx -t && sudo nginx -s reload
#
# After that, deploying/stopping apps is automatic: ATLAS rewrites the per-app
# snippets in {d}/ and reloads nginx for you.

map $http_upgrade $connection_upgrade {{
    default upgrade;
    ''      close;
}}

server {{
    listen 80;
    # "_" matches any host; replace with your domain, e.g. server_name atlas.example.com;
    server_name {server_name};

    client_max_body_size 0;          # allow large dataset uploads

    # ---- deployed apps: virtual directories (auto-managed) ----------------
{apps}
    # ---- the ATLAS portal + API (everything else) -------------------------
    location / {{
        proxy_pass {upstream};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600s;
        proxy_buffering off;
    }}
}}
"""


# --------------------------------------------------------------------------- #
# file sync
# --------------------------------------------------------------------------- #
def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _snapshot(directory: Path) -> dict[str, bytes]:
    if not directory.is_dir():
        return {}
    snap = {}
    for p in directory.glob(f"{SNIPPET_PREFIX}*.conf"):
        if p.is_file():
            try:
                snap[p.name] = p.read_bytes()
            except OSError:
                continue
    return snap


def _restore(directory: Path, snapshot: dict[str, bytes]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    current = {p.name for p in directory.glob(f"{SNIPPET_PREFIX}*.conf")}
    for name, data in snapshot.items():
        (directory / name).write_bytes(data)
        current.discard(name)
    for name in current:  # files we added that weren't in the snapshot
        try:
            (directory / name).unlink()
        except OSError:
            pass


def _run(cmd: list[str], timeout: float = 30.0) -> tuple[bool, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError) as exc:
        return False, str(exc)
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, out.strip()


def sync(routes: list[dict]) -> dict:
    """Regenerate all nginx files for ``routes`` and, if nginx is live, reload it.

    Returns a status dict used by the API/UI. Never raises: a proxy problem must
    not fail an otherwise successful deployment.
    """
    result: dict = {
        "generated": len(routes),
        "conf_dir": str(conf_dir()),
        "vhost": str(vhost_file()),
        "nginx_present": nginx_available(),
        "wrote_snippets": False,
        "reloaded": False,
        "status": "generated",
        "detail": "",
    }

    cdir = conf_dir()
    # 1) Per-app snippets: rewrite the dedicated directory from scratch.
    snapshot: dict[str, bytes] = {}
    try:
        snapshot = _snapshot(cdir)
        cdir.mkdir(parents=True, exist_ok=True)
        # Remove stale blocks for apps that are no longer running.
        for old in cdir.glob(f"{SNIPPET_PREFIX}*.conf"):
            old.unlink(missing_ok=True)
        for r in routes:
            safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in r["slug"])
            _write(cdir / f"{SNIPPET_PREFIX}{safe}.conf", app_snippet(r))
        result["wrote_snippets"] = True
    except OSError as exc:
        result["status"] = "error"
        result["detail"] = f"Could not write nginx snippets: {exc}"
        return result

    # 2) The standalone vhost (portal + API + every app).
    try:
        _write(vhost_file(), full_vhost(routes))
    except OSError as exc:
        # Not fatal: the snippets are the thing nginx includes.
        result["detail"] = f"vhost not written: {exc}"

    # 3) If nginx isn't installed, leave the files in storage for an operator.
    reload_cmd = _reload_command()
    if not reload_cmd:
        result["status"] = "files_ready"
        result["detail"] = (
            "nginx not detected on this host - config files were generated under "
            f"{settings.storage_dir / 'nginx'} and can be copied to nginx. "
            "Set ATLAS_NGINX_CONF_DIR / ATLAS_NGINX_RELOAD_CMD to reload automatically."
        )
        return result

    binary = shutil.which("nginx")
    test_cmd = [binary, "-t"] if binary else None

    # 4) Validate before reload; roll the snippets back on failure so a broken
    #    app can never take the reverse proxy (and the other apps) down.
    if test_cmd:
        ok, out = _run(test_cmd)
        if not ok:
            _restore(cdir, snapshot)
            result["status"] = "config_error"
            result["detail"] = "nginx -t failed after update; reverted. " + out[-600:]
            return result

    # 5) Graceful reload - starts new workers on the new config without dropping
    #    in-flight requests to the other apps.
    if settings.nginx_auto_reload:
        ok, out = _run(reload_cmd)
        result["reloaded"] = ok
        if ok:
            result["status"] = "active"
            result["detail"] = f"nginx reloaded; {len(routes)} app(s) served as virtual directories."
        else:
            result["status"] = "reload_failed"
            result["detail"] = "Config written but nginx reload failed: " + out[-600:]
    else:
        result["status"] = "files_ready"
        result["detail"] = "Config written; automatic reload disabled (ATLAS_NGINX_AUTO_RELOAD=false)."

    return result


def status() -> dict:
    """A lightweight summary for the UI: is nginx live and how many routes exist?"""
    cdir = conf_dir()
    snippets = sorted(p.name for p in cdir.glob(f"{SNIPPET_PREFIX}*.conf")) if cdir.is_dir() else []
    return {
        "nginx_present": nginx_available(),
        "auto_reload": settings.nginx_auto_reload,
        "conf_dir": str(cdir),
        "vhost": str(vhost_file()),
        "managed_snippets": len(snippets),
        "vhost_exists": vhost_file().exists(),
    }
