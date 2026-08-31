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

import os
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.core.config import settings

# A marker written into every managed file so it is obvious who owns it and so
# stale files from older ATLAS versions can be safely reclaimed.
MANAGED_TAG = "# Managed by ATLAS - do not edit by hand; regenerated on deploy."
# The ownership substring checked before overwriting anything in a real nginx
# directory: presence of this, not of the full tag, is what says "ATLAS owns it".
MANAGED_OWNER = "Managed by ATLAS"

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
# how an app's virtual directory is actually answered
# --------------------------------------------------------------------------- #
def serving_mode() -> str:
    """``"atlas+nginx"``, ``"atlas"``, ``"nginx"`` or ``"none"``.

    ATLAS always answers ``/<prefix>/<slug>/`` itself (see
    :mod:`app.services.app_proxy`), so ``nginx`` here means "an operator also
    keeps nginx in sync", never "nginx is required for the app to open".
    """
    parts = []
    if settings.deploy_builtin_proxy:
        parts.append("atlas")
    if nginx_available() or _install_target() is not None:
        parts.append("nginx")
    return "+".join(parts) or "none"


def probe(route: dict) -> dict:
    """Ask the app itself whether it is serving, bypassing every proxy in front.

    The portal shows this next to the Open button so "running" in the database and
    "answering HTTP" can never be confused with each other - the difference is
    exactly what a learner is stuck on when a Streamlit process is alive but still
    importing torch.
    """
    port = route.get("port")
    path = route.get("path") or ""
    if not port:
        return {"live": False, "detail": "no internal port (not deployed)"}
    health = f"/{path}/_stcore/health" if route.get("framework") == "streamlit" else f"/{path}/"
    try:
        with httpx.Client(timeout=httpx.Timeout(1.5, connect=0.6)) as client:
            resp = client.get(f"http://127.0.0.1:{port}{health}")
        ok = resp.status_code < 500
        return {"live": ok, "status_code": resp.status_code,
                "checked": health,
                "detail": "" if ok else f"HTTP {resp.status_code} from {health}"}
    except Exception as exc:  # noqa: BLE001 - a dead port is the common case
        return {"live": False, "checked": health, "detail": str(exc)[:200]}


# --------------------------------------------------------------------------- #
# optional: keep a vhost installed inside nginx
# --------------------------------------------------------------------------- #
def _is_managed(path: Path) -> bool:
    """True if ``path`` is absent or was written by ATLAS (never overwrite a
    hand-maintained file that happens to share our name)."""
    if not path.exists():
        return True
    try:
        head = path.read_text(errors="replace")[:400]
    except OSError:
        return False
    return MANAGED_OWNER in head


def _install_target() -> tuple[Path, Path | None] | None:
    """Where a generated vhost may be installed, or ``None``.

    Debian/Ubuntu split sites into ``sites-available`` + ``sites-enabled``; RHEL
    and Alpine just include ``conf.d`` into the ``http`` block. Both layouts are
    probed, and only a directory we can actually write is considered - a vhost
    that cannot be written is simply not installed, never an error.
    """
    if not settings.nginx_auto_install:
        return None
    available = Path(settings.nginx_sites_available or "")
    enabled = Path(settings.nginx_sites_enabled or "")
    if settings.nginx_sites_available and available.is_dir() and os.access(available, os.W_OK):
        return available, (enabled if enabled.is_dir() else None)
    confd = Path(settings.nginx_conf_d or "")
    if settings.nginx_conf_d and confd.is_dir() and os.access(confd, os.W_OK):
        return confd, None
    return None


def _install_vhost(routes: list[dict]) -> dict:
    """Write the generated vhost into nginx's own directory, if opted in.

    Returns a report; never raises. An existing ``atlas.conf`` that is not
    ATLAS-managed is left exactly as it is, because the operator's file always
    outranks ours.
    """
    report: dict = {"path": None, "enabled_link": False, "skipped": None, "backup": None}
    if not settings.nginx_auto_install:
        report["skipped"] = (
            "nginx install is opt-in (ATLAS_NGINX_AUTO_INSTALL); apps are already "
            "reachable through ATLAS's own proxy."
        )
        return report
    target = _install_target()
    if target is None:
        report["skipped"] = ("no writable nginx directory configured "
                             "(set ATLAS_NGINX_AUTO_INSTALL with sites-available or conf.d)")
        return report
    directory, link_dir = target
    dest = directory / VHOST_NAME
    if not _is_managed(dest):
        report["skipped"] = f"{dest} exists and is not ATLAS-managed; left untouched"
        return report
    try:
        # Kept so a rejected config can be put back exactly as it was: the live
        # nginx must never be left pointing at the config we just wrote.
        report["backup"] = dest.read_bytes() if dest.exists() else None
        dest.write_text(full_vhost(routes), encoding="utf-8")
        report["path"] = str(dest)
        if link_dir is not None:
            link = link_dir / VHOST_NAME
            if link.is_symlink() or link.exists():
                if link.is_symlink():
                    report["enabled_link"] = True
                else:
                    report["skipped"] = (f"{link} is a real file, not a symlink; "
                                         f"not replaced - write it yourself")
                    return report
            else:
                link.symlink_to(dest)
                report["enabled_link"] = True
    except OSError as exc:
        report["skipped"] = f"could not install vhost: {exc}"
        report["path"] = None
    return report


def _install_rollback(install: dict) -> None:
    """Put the installed vhost back after `nginx -t` rejected the new one."""
    path = install.get("path")
    if not path:
        return
    dest = Path(path)
    try:
        if install.get("backup") is None:
            dest.unlink(missing_ok=True)
        else:
            dest.write_bytes(install["backup"])
    except OSError:
        pass


def _uninstall_vhost() -> None:
    """Remove ATLAS's own vhost + link (used when the last app stops)."""
    target = _install_target()
    if target is None:
        return
    directory, link_dir = target
    dest = directory / VHOST_NAME
    if _is_managed(dest):
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass
    if link_dir is not None:
        link = link_dir / VHOST_NAME
        if link.is_symlink():
            try:
                link.unlink(missing_ok=True)
            except OSError:
                pass


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

    # 3) Optional: install the vhost into nginx itself. This is the step that
    #    used to be "copy this file in by hand", and it is deliberately opt-in -
    #    without it the apps are already reachable through ATLAS's own proxy.
    install = _install_vhost(routes)
    result["installed_to"] = install["path"]
    result["install_skipped"] = install["skipped"]

    # 4) If nginx isn't installed, leave the files in storage for an operator.
    #    This is not a failure: the built-in proxy is what serves the apps.
    reload_cmd = _reload_command()
    if not reload_cmd:
        result["status"] = "files_ready"
        if settings.deploy_builtin_proxy:
            result["detail"] = (
                f"{len(routes)} app(s) served as virtual directories by ATLAS at "
                f"/{settings.deploy_prefix}/<slug>/. nginx files were generated under "
                f"{settings.storage_dir / 'nginx'} for an optional proxy in front."
            )
        else:
            result["detail"] = (
                "nginx not detected and ATLAS's built-in proxy is disabled: config "
                f"files were generated under {settings.storage_dir / 'nginx'} and must "
                "be installed by an operator. Set ATLAS_DEPLOY_BUILTIN_PROXY=true to "
                "serve apps without nginx."
            )
        result["serving_mode"] = serving_mode()
        return result

    binary = shutil.which("nginx")
    test_cmd = [binary, "-t"] if binary else None

    # 5) Validate before reload; roll the snippets (and an installed vhost) back on
    #    failure so a broken app can never take the reverse proxy down.
    if test_cmd:
        ok, out = _run(test_cmd)
        if not ok:
            _restore(cdir, snapshot)
            _install_rollback(install)
            result["status"] = "config_error"
            result["detail"] = "nginx -t failed after update; reverted. " + out[-600:]
            result["serving_mode"] = serving_mode()
            return result

    # 6) Graceful reload - starts new workers on the new config without dropping
    #    in-flight requests to the other apps.
    if settings.nginx_auto_reload:
        ok, out = _run(reload_cmd)
        result["reloaded"] = ok
        if ok:
            result["status"] = "active"
            via = "nginx + ATLAS" if settings.deploy_builtin_proxy else "nginx"
            result["detail"] = (f"nginx reloaded; {len(routes)} app(s) served as "
                                f"virtual directories via {via}.")
        else:
            result["status"] = "reload_failed"
            result["detail"] = "Config written but nginx reload failed: " + out[-600:]
    else:
        result["status"] = "files_ready"
        result["detail"] = ("Config written; automatic reload disabled "
                            "(ATLAS_NGINX_AUTO_RELOAD=false). Apps stay reachable "
                            "through ATLAS's own proxy.")

    result["serving_mode"] = serving_mode()
    return result


def status() -> dict:
    """A summary for the UI: what serves an app's path, and how nginx is wired.

    Deliberately self-describing rather than a boolean to interpret: the portal
    used to reduce this to "nginx present / nginx absent", which read like a fault
    report on a perfectly healthy deployment.
    """
    cdir = conf_dir()
    snippets = sorted(p.name for p in cdir.glob(f"{SNIPPET_PREFIX}*.conf")) if cdir.is_dir() else []
    install = _install_target()
    installed = install[0] / VHOST_NAME if install else None
    return {
        "serving_mode": serving_mode(),
        "nginx_present": nginx_available(),
        "auto_reload": settings.nginx_auto_reload,
        "auto_install": bool(settings.nginx_auto_install),
        "installed_at": str(installed) if installed and installed.exists() else None,
        "conf_dir": str(cdir),
        "vhost": str(vhost_file()),
        "managed_snippets": len(snippets),
        "vhost_exists": vhost_file().exists(),
    }
