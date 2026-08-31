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
  * the generated compose mounts an isolated persistent data volume.

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
