"""One intern, one course, start to finish - driven entirely through the API.

This is the claim the user actually cares about: that a Topic 6 intern can go
from an empty account to a working, published Streamlit app without anyone
touching the filesystem for them. Nothing here is mocked. It:

  1. signs in and reads the assigned corrosion topic,
  2. checks the notebook the platform serves really contains the U-Net,
  3. completes every lesson and watches XP accrue,
  4. uploads the trained checkpoint as a real dataset asset,
  5. creates a deployment, uploads the Streamlit bundle, and deploys it,
  6. asserts the rubric scores 100 and the app auto-publishes to the portal,
  7. fetches the running app's own HTTP response to prove it is alive.

Needs a dev instance on :8000. Run after `train.py` has produced a checkpoint
under templates/corrosion_unet/runs/verify (tests/course_e2e.py --train does it).
"""
from __future__ import annotations

import io
import json
import mimetypes
import sys
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path

BASE = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "corrosion_unet"

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


def call(path: str, token: str | None = None, method: str = "GET",
         body: dict | None = None, raw: bytes | None = None,
         content_type: str | None = None, timeout: int = 120):
    req = urllib.request.Request(BASE + path, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = raw
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    if content_type:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, data, timeout=timeout) as r:
            payload = r.read()
            try:
                return r.status, json.loads(payload)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return r.status, payload
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, None
    except urllib.error.URLError as e:
        print(f"\n!! cannot reach {BASE}: {e}\n")
        sys.exit(2)


def multipart(fields: dict[str, str], files: list[tuple[str, str, bytes]]):
    """Build a multipart/form-data body with the stdlib only."""
    boundary = f"----atlas{uuid.uuid4().hex}"
    buf = io.BytesIO()
    for key, value in fields.items():
        buf.write(f"--{boundary}\r\n".encode())
        buf.write(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        buf.write(f"{value}\r\n".encode())
    for key, filename, content in files:
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        buf.write(f"--{boundary}\r\n".encode())
        buf.write(
            f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'.encode())
        buf.write(f"Content-Type: {ctype}\r\n\r\n".encode())
        buf.write(content)
        buf.write(b"\r\n")
    buf.write(f"--{boundary}--\r\n".encode())
    return buf.getvalue(), f"multipart/form-data; boundary={boundary}"


def build_bundle() -> bytes:
    """Zip the app exactly as notebook 5 assembles it: the Streamlit file, the
    shared kit it imports, the checkpoint, and the evaluation report."""
    app_dir = TEMPLATE.parent / "corrosion_app"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(app_dir / "app.py", "app.py")
        zf.write(app_dir / "requirements.txt", "requirements.txt")
        zf.write(TEMPLATE / "corrosion_kit.py", "corrosion_kit.py")
        run_dir = TEMPLATE / "runs" / "verify"
        if (run_dir / "best.pt").exists():
            zf.write(run_dir / "best.pt", "best.pt")
        for extra in ("report.json", "history.csv"):
            if (run_dir / extra).exists():
                zf.write(run_dir / extra, extra)
    return out.getvalue()


def main() -> int:
    print(f"\n{BOLD}One course, end to end{RESET}")
    print("=" * 74)

    # ---------------------------------------------------------- 1. sign in
    status, body = call("/api/auth/login", method="POST",
                        body={"email": "intern@atlas.id", "password": "intern123"})
    check("intern signs in", status == 200 and "access_token" in (body or {}), str(status))
    token = body["access_token"]

    status, topic = call("/api/topics/corrosion-segmentation", token)
    check("corrosion topic loads", status == 200 and topic.get("lesson_count") == 6,
          f"{topic.get('lesson_count')} lessons")
    topic_id = topic["id"]

    # ------------------------------------------------------- 2. the notebooks
    # The playground is the whole pipeline, one notebook per stage. An intern
    # who wants to look at a prediction must not have to re-run training.
    status, nbs = call("/api/notebooks?topic_id=%d" % topic_id, token)
    served = [nb for nb in nbs if nb["slug"].startswith("corrosion-")
              and not nb["slug"].endswith("playground")]
    expected = ["corrosion-1-eda", "corrosion-2-training", "corrosion-3-evaluation",
                "corrosion-4-inference", "corrosion-5-deployment"]
    check("topic serves the five-stage pipeline",
          status == 200 and [nb["slug"] for nb in served] == expected,
          ", ".join(nb["slug"] for nb in served))
    check("only the training stage demands a GPU",
          [nb["slug"] for nb in served if nb["requires_gpu"]] == ["corrosion-2-training"],
          ", ".join(nb["slug"] for nb in served if nb["requires_gpu"]) or "none")

    sources: dict[str, str] = {}
    for notebook in served:
        status, nb = call(f"/api/notebooks/{notebook['id']}", token)
        cells = nb.get("content", {}).get("cells", [])
        code = [c for c in cells if c["cell_type"] == "code"]
        sources[notebook["slug"]] = "\n".join(
            "".join(c["source"]) if isinstance(c["source"], list) else c["source"] for c in code)
        check(f"{notebook['slug']} served with its cells",
              status == 200 and len(cells) >= 10, f"{len(cells)} cells, {len(code)} code")

    every = "\n".join(sources.values())
    # Each notebook carries the library rather than importing one from the
    # platform, so it runs unchanged on a Colab that cannot reach this server.
    check("every notebook carries the shared library",
          all("KIT_SOURCE" in src and "class UNet" in src for src in sources.values()),
          "corrosion_kit embedded in all five")
    check("no dependency on an ATLAS-side package",
          "from app." not in every and "import app." not in every, "self-contained")
    check("runs without the injected bridge",
          all('if "atlas" not in dir():' in src for src in sources.values()),
          "each bootstrap supplies a stand-in")
    check("dataset layout is images/ + masks/",
          'IMAGE_DIRS' in every and '"masks"' in every, "matches the export")
    check("training loop present",
          "loss.backward()" in sources["corrosion-2-training"]
          and "optim" in sources["corrosion-2-training"].lower())
    check("training resumes instead of restarting",
          "resuming from epoch" in sources["corrosion-2-training"]
          and "save_checkpoint" in sources["corrosion-2-training"],
          "checkpoint + resume")
    check("checkpoints survive a Colab disconnect",
          "drive.mount" in sources["corrosion-2-training"]
          and "TIME_BUDGET_MIN" in sources["corrosion-2-training"],
          "Drive + time budget")
    check("evaluation present",
          "mean_iou" in sources["corrosion-3-evaluation"]
          and "ConfusionMatrix" in sources["corrosion-3-evaluation"])
    check("inference produces confidence",
          "mean_confidence" in sources["corrosion-4-inference"])
    check("deployment builds the app bundle",
          "APP_SOURCE" in sources["corrosion-5-deployment"]
          and "best.pt" in sources["corrosion-5-deployment"])

    # ---------------------------------------------------------- 3. lessons
    status, detail = call("/api/topics/corrosion-segmentation", token)
    lessons = detail["lessons"]
    xp_before = call("/api/progress/me", token)[1].get("xp", 0)
    for lesson in lessons:
        call(f"/api/lessons/{lesson['id']}/complete", token, method="POST")
    status, prog = call("/api/progress/me", token)
    xp_after = prog.get("xp", 0)
    # Re-running the suite must not fail just because the lessons are already
    # done: what matters is that XP was awarded and never went backwards.
    check("all 6 lessons completed and XP awarded",
          status == 200 and xp_after >= xp_before and xp_after >= 195,
          f"XP {xp_before} -> {xp_after}")

    status, detail = call("/api/topics/corrosion-segmentation", token)
    done = sum(1 for l in detail["lessons"] if l["completed"])
    check("topic reports 6/6 complete", done == 6, f"{done}/6")

    # ---------------------------------------------------------- 4. artifact
    ckpt = TEMPLATE / "runs" / "verify" / "best.pt"
    if not ckpt.exists():
        check("trained checkpoint exists", False, "run train.py first")
        return 1
    payload, ctype = multipart(
        {"kind": "artifact", "topic_id": str(topic_id),
         "title": "corrosion_unet_best.pt",
         "description": "U-Net trained from the playground notebook."},
        [("file", "best.pt", ckpt.read_bytes())])
    status, asset = call("/api/assets", token, method="POST", raw=payload, content_type=ctype)
    check("trained checkpoint uploaded as an asset", status == 201,
          f"{status} {asset.get('size_bytes', 0) / 1e6:.1f} MB" if isinstance(asset, dict) else str(status))

    status, assets = call(f"/api/assets?topic_id={topic_id}", token)
    check("checkpoint appears in the dataset history",
          any(a["kind"] == "artifact" for a in assets), f"{len(assets)} assets")

    # ---------------------------------------------------------- 5. deploy
    status, dep = call("/api/deployments", token, method="POST", body={
        "topic_id": topic_id,
        "name": "Corrosion Segmentation Inspector",
        "framework": "streamlit",
        "entrypoint": "app.py",
        "description": "Pixel-level corrosion typing with confidence and charts.",
        "whimsical_url": "https://whimsical.com/atlas-corrosion-review",
    })
    check("deployment created", status == 201, str(status))
    dep_id = dep["id"]

    bundle = build_bundle()
    payload, ctype = multipart({}, [("file", "bundle.zip", bundle)])
    status, dep = call(f"/api/deployments/{dep_id}/bundle", token, method="POST",
                       raw=payload, content_type=ctype)
    check("app bundle uploaded", status == 200, f"{status} {len(bundle) / 1e6:.1f} MB")

    status, dep = call(f"/api/deployments/{dep_id}/check", token, method="POST")
    score = dep.get("readiness_score", 0) if isinstance(dep, dict) else 0
    check("rubric check runs", status == 200, str(status))
    check("app scores 100 on the graduation rubric", score == 100, f"score={score}")

    print(f"{DIM}  deploying (installs streamlit into an isolated venv, be patient){RESET}")
    status, dep = call(f"/api/deployments/{dep_id}/deploy", token, method="POST", timeout=900)
    check("deploy call succeeds", status == 200, str(status))
    check("deployment reaches RUNNING", dep.get("status") == "running", str(dep.get("status")))
    check("app auto-published to the portal", dep.get("published_to_portal") is True)
    url = dep.get("url") or ""
    check("deployment exposes a URL", bool(url), url)

    # ---------------------------------------------------------- 6. portal
    # The portal page reads /api/deployments and shows the published ones.
    status, all_deps = call("/api/deployments", token)
    portal = [d for d in all_deps if d.get("published_to_portal")] if isinstance(all_deps, list) else []
    listed = [d for d in portal if d.get("id") == dep_id]
    check("app is listed in the App Portal", bool(listed), f"{len(portal)} published apps")

    # ---------------------------------------------------------- 7. it lives
    port = url.rsplit(":", 1)[-1].split("/")[0] if ":" in url else ""
    alive = False
    body_text = ""
    if port.isdigit():
        for _ in range(30):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as r:
                    body_text = r.read(4000).decode("utf-8", "replace")
                    alive = r.status == 200
                    break
            except Exception:
                time.sleep(2)
    check("the deployed app answers HTTP 200", alive, f"port {port}")
    check("and it is a Streamlit page", "streamlit" in body_text.lower(),
          f"{len(body_text)} bytes")

    print("\n" + "=" * 74)
    total = _passed + _failed
    colour = GREEN if not _failed else RED
    print(f"{colour}{BOLD}=== {_passed}/{total} passed ==={RESET}")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
