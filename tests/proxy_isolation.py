#!/usr/bin/env python
"""Unit checks for automatic nginx virtual directories + per-app data isolation.

Runs without a server and without nginx installed - it verifies:

  * every running app is rendered as its own /<prefix>/<slug>/ virtual directory
    and the full vhost still proxies the portal/API to the backend;
  * sync() writes one managed snippet per app, removes blocks for apps that are
    no longer running (so nginx never points at a dead app), and touches no files
    that are not ATLAS-managed;
  * each app gets a distinct persistent data directory, and every cache/config/
    temp path in its environment is pinned inside that directory (apps can't see
    each other's data);
  * the generated compose mounts an isolated persistent data volume;
  * the built-in proxy is reported as what serves an app, and the optional nginx
    vhost install writes only its own file, links it, and yields to any file the
    operator maintains.

    python tests/proxy_isolation.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.domain.enums import AppFramework  # noqa: E402
from app.services import deployments as ds  # noqa: E402
from app.services import proxy  # noqa: E402

_results: list[tuple[bool, str]] = []


def check(name: str, ok: bool) -> None:
    _results.append((ok, name))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")


ROUTES = [
    {"slug": "corrosion-unet", "name": "Corrosion UNet", "framework": "streamlit",
     "port": 8601, "path": "app/corrosion-unet", "url": ""},
    {"slug": "failure-predictor", "name": "Failure Predictor", "framework": "gradio",
     "port": 8602, "path": "app/failure-predictor", "url": ""},
]


def test_vhost_render() -> None:
    vh = proxy.full_vhost(ROUTES)
    check("vhost has each app's virtual-directory location",
          "location ^~ /app/corrosion-unet/" in vh
          and "location ^~ /app/failure-predictor/" in vh)
    check("vhost proxies each path to the right internal port",
          "proxy_pass http://127.0.0.1:8601/app/corrosion-unet/;" in vh
          and "proxy_pass http://127.0.0.1:8602/app/failure-predictor/;" in vh)
    check("vhost still proxies the portal/API to the upstream",
          "location / {" in vh and proxy.settings.nginx_upstream in vh)
    check("vhost includes websocket upgrade map",
          "map $http_upgrade $connection_upgrade" in vh)
    check("per-app snippet is labelled and names the app",
          proxy.MANAGED_TAG in proxy.app_snippet(ROUTES[0])
          and "/app/corrosion-unet/" in proxy.app_snippet(ROUTES[0]))


def test_sync_lifecycle(tmp: Path) -> None:
    proxy.settings.storage_dir = tmp / "storage"
    proxy.settings.nginx_conf_dir = ""
    proxy.settings.nginx_vhost_file = ""

    # A file nginx/admin owns must never be removed by ATLAS.
    cdir = proxy.conf_dir()
    cdir.mkdir(parents=True, exist_ok=True)
    foreign = cdir / "other-site.conf"
    foreign.write_text("# not managed by ATLAS\n")

    res = proxy.sync(ROUTES)
    snippets = sorted(p.name for p in cdir.glob("*.conf"))
    check("sync writes one snippet per running app", len(
        [s for s in snippets if s.startswith(proxy.SNIPPET_PREFIX)]) == 2)
    check("sync leaves foreign (non-ATLAS) nginx files untouched",
          foreign.exists() and foreign.read_text() == "# not managed by ATLAS\n")
    check("sync writes the standalone vhost", proxy.vhost_file().exists())
    check("sync without nginx reports files_ready (never fails)",
          res["status"] == "files_ready" and res["wrote_snippets"] is True)
    check("sync without nginx is no longer worded like a fault",
          "not detected" not in res["detail"].lower()
          and "ATLAS" in res["detail"])

    # Stop one app: its block must disappear, the other stays.
    proxy.sync(ROUTES[:1])
    remaining = sorted(p.name for p in cdir.glob(f"{proxy.SNIPPET_PREFIX}*.conf"))
    check("stopping an app removes only its snippet",
          remaining == ["atlas-app-corrosion-unet.conf"])
    check("foreign file still present after resync", foreign.exists())

    # Snippet content routes correctly.
    body = (cdir / remaining[0]).read_text()
    check("remaining snippet routes the still-running app",
          "proxy_pass http://127.0.0.1:8601/app/corrosion-unet/;" in body)


def test_serving_layers(tmp: Path) -> None:
    """What the app path is actually answered by, and the opt-in nginx install."""
    proxy.settings.storage_dir = tmp / "storage"
    proxy.settings.nginx_conf_dir = ""
    proxy.settings.nginx_vhost_file = ""
    proxy.settings.nginx_reload_cmd = ""
    original = (proxy.settings.deploy_builtin_proxy, proxy.settings.nginx_auto_install,
                proxy.settings.nginx_sites_available, proxy.settings.nginx_sites_enabled,
                proxy.settings.nginx_conf_d)
    try:
        # The built-in proxy is the default answer for /<prefix>/<slug>/.
        proxy.settings.deploy_builtin_proxy = True
        proxy.settings.nginx_auto_install = False
        check("serving mode reports ATLAS as the proxy by default",
              proxy.serving_mode() == "atlas")
        stat = proxy.status()
        check("status reports the serving mode, not just 'is nginx there'",
              stat["serving_mode"] == "atlas" and "auto_install" in stat
              and stat["installed_at"] is None)

        res = proxy.sync(ROUTES)
        check("with no nginx the run still reports success for the apps",
              res["status"] == "files_ready" and "served as virtual directories by ATLAS"
              in res["detail"])
        check("and it says the nginx install is opt-in, not missing",
              res["install_skipped"] and "ATLAS_NGINX_AUTO_INSTALL" in res["install_skipped"])

        proxy.settings.deploy_builtin_proxy = False
        check("turning the built-in proxy off is visible in the detail text",
              "built-in proxy is disabled" in proxy.sync(ROUTES)["detail"])
        proxy.settings.deploy_builtin_proxy = True

        # Opt-in install, Debian layout: write + enable, nothing else touched.
        avail = tmp / "sites-available"
        enabled = tmp / "sites-enabled"
        avail.mkdir()
        enabled.mkdir()
        foreign = avail / "other-site.conf"
        foreign.write_text("server {}\n")
        proxy.settings.nginx_auto_install = True
        proxy.settings.nginx_sites_available = str(avail)
        proxy.settings.nginx_sites_enabled = str(enabled)
        proxy.settings.nginx_conf_d = ""
        res = proxy.sync(ROUTES)
        installed = avail / proxy.VHOST_NAME
        check("auto-install writes the vhost into sites-available",
              installed.exists() and "location ^~ /app/corrosion-unet/" in installed.read_text())
        check("auto-install enables it with a symlink in sites-enabled",
              (enabled / proxy.VHOST_NAME).is_symlink()
              and res["installed_to"] == str(installed))
        check("auto-install leaves other sites in the directory alone",
              foreign.read_text() == "server {}\n")
        check("installing the vhost makes the serving mode honest about it",
              proxy.serving_mode() == "atlas+nginx")

        # A file the operator maintains wins over ours, always.
        installed.write_text("server { listen 80; }  # hand-written\n")
        res = proxy.sync(ROUTES)
        check("a non-ATLAS atlas.conf is never overwritten",
              "hand-written" in installed.read_text()
              and "not ATLAS-managed" in res["install_skipped"])

        # ...but ours is regenerated, and the install survives that rewrite.
        installed.write_text(proxy.MANAGED_TAG + "\nserver { stale }\n")
        proxy.sync(ROUTES)
        check("an ATLAS-managed atlas.conf is refreshed on the next sync",
              "atlas-app-corrosion-unet" not in installed.read_text()
              and "location ^~ /app/failure-predictor/" in installed.read_text())

        # RHEL/Alpine layout: no sites-available, just an included conf.d.
        proxy.settings.nginx_auto_install = True
        proxy.settings.nginx_sites_available = ""
        proxy.settings.nginx_sites_enabled = ""
        confd = tmp / "conf.d"
        confd.mkdir()
        proxy.settings.nginx_conf_d = str(confd)
        check("conf.d is used when the host has no sites-available",
              proxy._install_vhost(ROUTES)["path"] == str(confd / proxy.VHOST_NAME)
              and (confd / proxy.VHOST_NAME).exists())

        # A directory we cannot write is not an error, just not installed.
        proxy.settings.nginx_sites_available = str(tmp / "does-not-exist")
        proxy.settings.nginx_conf_d = ""
        check("a missing nginx directory skips instead of failing",
              proxy._install_target() is None)

        # Liveness probing answers the question the portal shows.
        check("probe reports a dead port without raising",
              proxy.probe({"slug": "x", "path": "app/x", "port": 1,
                           "framework": "streamlit"})["live"] is False)
        check("probe explains a deployment that has no port at all",
              "no internal port" in proxy.probe({"slug": "x", "path": "app/x",
                                                 "port": None})["detail"])
    finally:
        (proxy.settings.deploy_builtin_proxy, proxy.settings.nginx_auto_install,
         proxy.settings.nginx_sites_available, proxy.settings.nginx_sites_enabled,
         proxy.settings.nginx_conf_d) = original


def test_data_isolation(tmp: Path) -> None:
    ds.settings.storage_dir = tmp / "storage"
    a = SimpleNamespace(id=21, slug="corrosion-unet", framework=AppFramework.STREAMLIT)
    b = SimpleNamespace(id=22, slug="failure-predictor", framework=AppFramework.GRADIO)

    da, db = ds.app_data_dir(a), ds.app_data_dir(b)
    check("each app gets a distinct persistent data dir under appdata/",
          da != db and da.parent.name == "appdata" and db.parent.name == "appdata")

    ea = ds._app_runtime_env(a, 8601, "app/corrosion-unet")
    eb = ds._app_runtime_env(b, 8602, "app/failure-predictor")

    keys = ("ATLAS_APP_DATA_DIR", "APP_DATA_DIR", "XDG_CACHE_HOME",
            "XDG_CONFIG_HOME", "XDG_DATA_HOME", "TMPDIR", "HOME", "HF_HOME",
            "TORCH_HOME", "MPLCONFIGDIR")
    isolated = True
    for k in keys:
        in_a = str(da) in ea[k]
        in_b = str(db) in eb[k]
        cross = str(da) in eb[k] or str(db) in ea[k]
        isolated = isolated and in_a and in_b and not cross
    check("all cache/config/temp paths are isolated per app", isolated)
    check("gradio gets GRADIO_ROOT_PATH; streamlit does not",
          eb.get("GRADIO_ROOT_PATH") == "/app/failure-predictor"
          and "GRADIO_ROOT_PATH" not in ea)

    probe = Path(ea["TMPDIR"]) / "probe.txt"
    probe.write_text("ok")
    check("isolated temp dir exists and is writable", probe.read_text() == "ok")


def test_compose_volume(tmp: Path) -> None:
    root = tmp / "bundle"
    root.mkdir(parents=True, exist_ok=True)
    ds.ensure_scaffold(root, AppFramework.STREAMLIT, "app.py", 8610, "app/my-app")
    compose = (root / "docker-compose.yml").read_text()
    check("generated compose mounts an isolated persistent /data volume",
          "app-data:/data" in compose and "ATLAS_APP_DATA_DIR=/data" in compose)


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        print("proxy vhost rendering:")
        test_vhost_render()
        print("proxy sync lifecycle:")
        test_sync_lifecycle(tmp / "p")
        print("serving layers (built-in proxy + optional nginx install):")
        test_serving_layers(tmp / "s")
        print("per-app data isolation:")
        test_data_isolation(tmp / "d")
        print("container data volume:")
        test_compose_volume(tmp / "c")

    failed = [n for ok, n in _results if not ok]
    print(f"\n{len(_results) - len(failed)}/{len(_results)} checks passed")
    if failed:
        print("FAILED:")
        for n in failed:
            print("  -", n)
        return 1
    print("ALL PROXY/ISOLATION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
