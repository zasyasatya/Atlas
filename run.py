#!/usr/bin/env python3
"""
ATLAS launcher - runs the whole platform on a machine with no Docker.

    python run.py                 first run: set everything up, then serve
    python run.py --build         force a frontend rebuild, then serve
    python run.py --backend-only  API only (skip the UI build)
    python run.py --dev           backend + Next.js dev server (hot reload)
    python run.py --port 9000     serve on a different port
    python run.py --check         diagnose the environment and exit

Only Python 3.10+ is required. Node.js is optional: without it, ATLAS serves a
prebuilt UI if one is present, and otherwise runs headless as an API.

This script is dependency-free by design - it must run *before* anything is
installed, so it uses nothing outside the standard library.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
STATIC = BACKEND / "app" / "static"
VENV = ROOT / ".venv"
MIN_PY = (3, 10)

IS_WIN = os.name == "nt"
G, Y, R, B, DIM, RESET = "\033[32m", "\033[33m", "\033[31m", "\033[34m", "\033[2m", "\033[0m"
if IS_WIN and not os.environ.get("WT_SESSION"):
    G = Y = R = B = DIM = RESET = ""  # legacy consoles render escapes literally


def say(msg: str, colour: str = "") -> None:
    print(f"{colour}{msg}{RESET}", flush=True)


def step(n: int, total: int, msg: str) -> None:
    say(f"\n[{n}/{total}] {msg}", B)


def venv_bin(name: str) -> Path:
    """Path to an executable inside the project venv."""
    if IS_WIN:
        return VENV / "Scripts" / f"{name}.exe"
    return VENV / "bin" / name


def run(cmd: list[str] | str, cwd: Path | None = None, check: bool = True,
        quiet: bool = False, shell: bool = False) -> int:
    """Run a command, streaming output unless quiet."""
    printable = cmd if isinstance(cmd, str) else " ".join(str(c) for c in cmd)
    say(f"  $ {printable}", DIM)
    kw: dict = {"cwd": str(cwd) if cwd else None, "shell": shell}
    if quiet:
        kw["stdout"] = subprocess.DEVNULL
        kw["stderr"] = subprocess.STDOUT
    proc = subprocess.run(cmd, **kw)
    if check and proc.returncode != 0:
        raise SystemExit(f"{R}Command failed ({proc.returncode}): {printable}{RESET}")
    return proc.returncode


def have(binary: str) -> str | None:
    """Locate a binary, tolerating Windows' npm.cmd shim."""
    found = shutil.which(binary)
    if not found and IS_WIN:
        found = shutil.which(f"{binary}.cmd")
    return found


# --------------------------------------------------------------------------
# environment
# --------------------------------------------------------------------------
def check_python() -> None:
    if sys.version_info < MIN_PY:
        raise SystemExit(
            f"{R}Python {MIN_PY[0]}.{MIN_PY[1]}+ required, found "
            f"{sys.version_info.major}.{sys.version_info.minor}.{RESET}\n"
            f"Install a newer Python from https://python.org/downloads"
        )


def ensure_venv() -> Path:
    """Create .venv if absent and return its interpreter."""
    py = venv_bin("python")
    if py.exists():
        say(f"  virtualenv ready  {DIM}{VENV}{RESET}", G)
        return py
    say("  creating virtualenv (.venv) ...")
    try:
        venv.EnvBuilder(with_pip=True, clear=False).create(VENV)
    except Exception as exc:  # Debian/Ubuntu ship python3 without venv
        raise SystemExit(
            f"{R}Could not create a virtualenv: {exc}{RESET}\n"
            f"On Debian/Ubuntu install it first:  sudo apt install python3-venv"
        )
    if not py.exists():
        raise SystemExit(f"{R}Virtualenv created but {py} is missing.{RESET}")
    say("  virtualenv created", G)
    return py


def deps_installed(py: Path) -> bool:
    """True when the venv already satisfies the imports we need."""
    probe = "import fastapi, uvicorn, sqlmodel, jose, pandas, pptx, nbformat, nbclient"
    return subprocess.run([str(py), "-c", probe],
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def install_deps(py: Path, force: bool = False) -> None:
    if not force and deps_installed(py):
        say("  python dependencies already satisfied", G)
        return
    say("  installing python dependencies (1-3 min on first run) ...")
    run([str(py), "-m", "pip", "install", "--upgrade", "pip", "--quiet"], check=False)
    run([str(py), "-m", "pip", "install", "-r",
         str(BACKEND / "requirements.txt"), "--quiet"])
    if not deps_installed(py):
        raise SystemExit(f"{R}Dependencies installed but imports still fail.{RESET}")
    say("  python dependencies installed", G)


# --------------------------------------------------------------------------
# frontend
# --------------------------------------------------------------------------
def ui_present() -> bool:
    return (STATIC / "index.html").is_file()


STAMP = STATIC / ".build-stamp"

# Source that ends up inside the compiled bundle. node_modules, .next and out
# are deliberately excluded - they are build inputs/outputs, not source.
_SRC_DIRS = ("app", "lib", "public")
_SRC_FILES = ("package.json", "package-lock.json", "next.config.js",
              "tailwind.config.ts", "tsconfig.json", "postcss.config.js")


def _source_fingerprint() -> str:
    """Content hash of every frontend source file (~2 MB, a few milliseconds)."""
    h = hashlib.sha256()
    paths: list[Path] = [FRONTEND / f for f in _SRC_FILES]
    for d in _SRC_DIRS:
        root = FRONTEND / d
        if root.is_dir():
            paths.extend(p for p in root.rglob("*") if p.is_file())
    for p in sorted(paths, key=lambda x: str(x)):
        if not p.is_file():
            continue
        try:
            h.update(str(p.relative_to(FRONTEND)).encode())
            h.update(p.read_bytes())
        except OSError:
            continue
    return h.hexdigest()


def ui_stale() -> bool:
    """
    True when the compiled bundle no longer matches the source.

    The bundle is gitignored, so `git pull` updates the source but never the
    compiled output. Without this check the server would keep serving the old
    interface and new pages would appear to be missing.
    """
    if not ui_present():
        return True
    try:
        return STAMP.read_text(encoding="utf-8").strip() != _source_fingerprint()
    except OSError:
        return True  # no stamp: built by an older run.py or by Docker


def build_frontend(force: bool = False) -> bool:
    """Compile the Next.js export into backend/app/static. Returns success."""
    if ui_present() and not force:
        if not ui_stale():
            say("  UI bundle is up to date", G)
            return True
        if not have("npm"):
            # Nothing we can do, but never fail silently: a stale bundle is
            # exactly what makes a freshly pulled page look missing.
            say("  UI bundle is OUT OF DATE and Node.js is not installed.", Y)
            say("    Serving the previous build - newly added pages will 404.", Y)
            say("    Install Node 18+ from https://nodejs.org, then: python run.py --build", Y)
            return True
        say("  source changed since the last build - recompiling", Y)

    npm = have("npm")
    if not npm:
        say("  Node.js/npm not found - skipping the UI build.", Y)
        say("    Install Node 18+ from https://nodejs.org to get the web interface.", Y)
        say("    The API will still run and serve /api/docs.", Y)
        return False

    node_v = subprocess.run([have("node") or "node", "-v"],
                            capture_output=True, text=True).stdout.strip()
    say(f"  node {node_v}, npm {subprocess.run([npm, '-v'], capture_output=True, text=True).stdout.strip()}")

    if not (FRONTEND / "node_modules").is_dir():
        say("  installing npm packages (2-5 min on first run) ...")
        lock = FRONTEND / "package-lock.json"
        # npm ci is reproducible but hard-fails if the lockfile drifts.
        if lock.is_file() and run([npm, "ci"], cwd=FRONTEND, check=False) != 0:
            say("  npm ci failed, falling back to npm install", Y)
            run([npm, "install"], cwd=FRONTEND)
        elif not lock.is_file():
            run([npm, "install"], cwd=FRONTEND)
    else:
        say("  npm packages already installed", G)

    say("  building the Next.js static export ...")
    env = {**os.environ, "BUILD_EXPORT": "1", "NEXT_TELEMETRY_DISABLED": "1"}
    proc = subprocess.run([npm, "run", "build"], cwd=str(FRONTEND), env=env)
    if proc.returncode != 0:
        say("  frontend build failed - continuing with the API only.", R)
        return False

    out = FRONTEND / "out"
    if not (out / "index.html").is_file():
        say(f"  build produced no export at {out}", R)
        return False

    if STATIC.exists():
        shutil.rmtree(STATIC)
    shutil.copytree(out, STATIC)
    # Record what this bundle was built from, so the next start can tell
    # whether a pull has invalidated it.
    try:
        STAMP.write_text(_source_fingerprint(), encoding="utf-8")
    except OSError:
        pass
    say(f"  UI compiled into {STATIC.relative_to(ROOT)}", G)
    return True


# --------------------------------------------------------------------------
# serve
# --------------------------------------------------------------------------
def ensure_env_file() -> None:
    """Generate .env with a real secret key on first run."""
    env_path = ROOT / ".env"
    if env_path.exists():
        return
    import secrets
    sample = ROOT / ".env.example"
    text = sample.read_text(encoding="utf-8") if sample.exists() else ""
    text = text.replace("ATLAS_SECRET_KEY=generate-a-long-random-string",
                        f"ATLAS_SECRET_KEY={secrets.token_urlsafe(48)}")
    # Local runs are same-origin; a stale public URL breaks the GPU callback.
    text = text.replace(
        "ATLAS_PUBLIC_BASE_URL=https://atlas.yourdomain.com   # remote notebooks call back here",
        "ATLAS_PUBLIC_BASE_URL=")
    env_path.write_text(text, encoding="utf-8")
    say(f"  wrote .env with a freshly generated secret key", G)


def serve(py: Path, host: str, port: int, reload: bool, has_ui: bool) -> None:
    for sub in ("datasets", "decks", "artifacts", "deployments", "notebooks", "appdata", "nginx"):
        (ROOT / "storage" / sub).mkdir(parents=True, exist_ok=True)

    shown = "localhost" if host in ("0.0.0.0", "127.0.0.1") else host
    say("\n" + "=" * 62, G)
    say("  ATLAS is starting", G)
    say("=" * 62, G)
    if has_ui:
        say(f"  Web app   http://{shown}:{port}")
    else:
        say(f"  API only  http://{shown}:{port}   (no UI bundle)", Y)
    say(f"  API docs  http://{shown}:{port}/api/docs")
    say(f"  Health    http://{shown}:{port}/api/health")
    say("\n  Demo sign-in")
    say("    supervisor@atlas.id / supervisor123   authors curriculum")
    say("    intern@atlas.id     / intern123       runs notebooks, ships apps")
    say("\n  Stop with Ctrl+C", DIM)
    say("=" * 62 + "\n", G)

    cmd = [str(py), "-m", "uvicorn", "app.main:app", "--host", host, "--port", str(port)]
    if reload:
        cmd.append("--reload")
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    try:
        subprocess.run(cmd, cwd=str(BACKEND), env=env)
    except KeyboardInterrupt:
        say("\nATLAS stopped.", Y)


def serve_dev(py: Path, port: int) -> None:
    """Backend + Next dev server, for editing the UI with hot reload."""
    npm = have("npm")
    if not npm:
        raise SystemExit(f"{R}--dev needs Node.js. Install Node 18+ or drop --dev.{RESET}")
    if not (FRONTEND / "node_modules").is_dir():
        run([npm, "install"], cwd=FRONTEND)

    for sub in ("datasets", "decks", "artifacts", "deployments", "notebooks", "appdata", "nginx"):
        (ROOT / "storage" / sub).mkdir(parents=True, exist_ok=True)

    say("\n" + "=" * 62, G)
    say("  ATLAS dev mode", G)
    say("=" * 62, G)
    say(f"  UI (hot reload)  http://localhost:3000    <- use this one")
    say(f"  API              http://localhost:{port}")
    say("  Stop with Ctrl+C", DIM)
    say("=" * 62 + "\n", G)

    api = subprocess.Popen(
        [str(py), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
         "--port", str(port), "--reload"],
        cwd=str(BACKEND), env={**os.environ, "PYTHONUNBUFFERED": "1"})
    try:
        subprocess.run([npm, "run", "dev"], cwd=str(FRONTEND),
                       env={**os.environ, "NEXT_TELEMETRY_DISABLED": "1"})
    except KeyboardInterrupt:
        pass
    finally:
        api.terminate()
        try:
            api.wait(timeout=10)
        except subprocess.TimeoutExpired:
            api.kill()
        say("\nATLAS stopped.", Y)


def diagnose() -> None:
    say("ATLAS environment check\n", B)
    ok = True

    v = sys.version_info
    good = v >= MIN_PY
    ok &= good
    say(f"  {'PASS' if good else 'FAIL'}  Python {v.major}.{v.minor}.{v.micro}"
        f"{'' if good else f'  (need {MIN_PY[0]}.{MIN_PY[1]}+)'}", G if good else R)
    say(f"  ....  Platform {platform.system()} {platform.machine()}")

    node = have("node")
    if node:
        nv = subprocess.run([node, "-v"], capture_output=True, text=True).stdout.strip()
        say(f"  PASS  Node {nv}", G)
    else:
        say("  WARN  Node.js not found - UI cannot be built (API still works)", Y)

    say(f"  {'PASS' if VENV.exists() else '....'}  virtualenv "
        f"{'ready' if VENV.exists() else 'not created yet'}", G if VENV.exists() else "")
    if VENV.exists():
        py = venv_bin("python")
        d = deps_installed(py)
        say(f"  {'PASS' if d else 'WARN'}  python deps {'installed' if d else 'missing'}",
            G if d else Y)
    if not ui_present():
        say("  WARN  UI bundle not built", Y)
    elif ui_stale():
        say("  WARN  UI bundle is STALE - source changed since it was built", Y)
        say("        run: python run.py --build", Y)
    else:
        say("  PASS  UI bundle up to date", G)

    db = ROOT / "storage" / "atlas.db"
    say(f"  {'PASS' if db.exists() else '....'}  database "
        f"{'exists' if db.exists() else 'will be created on first run'}",
        G if db.exists() else "")

    say(f"\n  {'Ready. Run: python run.py' if ok else 'Fix the FAIL items above.'}",
        G if ok else R)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Run ATLAS without Docker.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    ap.add_argument("--build", action="store_true", help="force a frontend rebuild")
    ap.add_argument("--backend-only", action="store_true", help="skip the UI build")
    ap.add_argument("--dev", action="store_true", help="run Next dev server with hot reload")
    ap.add_argument("--check", action="store_true", help="diagnose the environment and exit")
    ap.add_argument("--reinstall", action="store_true", help="reinstall python dependencies")
    ap.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1)")
    ap.add_argument("--port", type=int, default=8000, help="port (default 8000)")
    args = ap.parse_args()

    if args.check:
        diagnose()
        return

    say("=" * 62, B)
    say("  ATLAS - AI Internship Operating System", B)
    say("=" * 62, B)

    total = 3 if args.backend_only else 4
    step(1, total, "Checking Python")
    check_python()
    say(f"  Python {sys.version_info.major}.{sys.version_info.minor}."
        f"{sys.version_info.micro} on {platform.system()}", G)

    step(2, total, "Preparing the virtualenv")
    py = ensure_venv()
    install_deps(py, force=args.reinstall)
    ensure_env_file()

    has_ui = False
    if not args.backend_only:
        step(3, total, "Preparing the web interface")
        has_ui = build_frontend(force=args.build)

    step(total, total, "Starting ATLAS")
    if args.dev:
        serve_dev(py, args.port)
    else:
        serve(py, args.host, args.port, reload=False, has_ui=has_ui or ui_present())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        say("\nInterrupted.", Y)
        sys.exit(130)
