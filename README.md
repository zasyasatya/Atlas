# ATLAS — AI Internship Operating System

End-to-end platform for running an AI internship programme: author curriculum without code, run
notebooks on borrowed GPUs, manage datasets, and ship graded Streamlit/Gradio apps.

FastAPI + Next.js monolith. One image, one port, deployable to Coolify.

---

## Quick start — no Docker needed

One command. It creates the virtualenv, installs dependencies, builds the UI,
seeds the database and starts the server.

```bash
python run.py
```

Then open **http://localhost:8000**.

New to the platform? The built-in manual at **http://localhost:8000/manual** is a
14-chapter walkthrough with screenshots of the real interface. It is linked from
the sign-in page and needs no account.

On Windows you can double-click `start.bat`; on macOS/Linux, `./start.sh`.

**Requirements:** Python 3.10+ is mandatory. Node.js 18+ is optional — it is
only needed to compile the web interface. Without Node, ATLAS still runs as an
API (`/api/docs`) and serves a prebuilt UI if one is present.

First run takes 3–6 minutes (downloading Python and npm packages). Later starts
take a few seconds.

### Other ways to run it

```bash
python run.py --check          # diagnose the environment, change nothing
python run.py --build          # force a UI rebuild after editing the frontend
python run.py --dev            # hot-reload dev mode (UI on :3000, API on :8000)
python run.py --backend-only   # API only, skip the UI build
python run.py --port 9000      # different port
python run.py --host 0.0.0.0   # expose on the local network
```

### Or with Docker

```bash
docker compose up --build     # http://localhost:8000
```

### Demo accounts

| Role | Email | Password |
|---|---|---|
| Supervisor | `supervisor@atlas.id` | `supervisor123` |
| Intern | `intern@atlas.id` | `intern123` |
| Admin | `admin@atlas.id` | `admin123` |

---

## What it does

**Curriculum CMS** — Supervisors compose lessons from eight block types (text, callout, clickable
architecture diagram, quiz, flashcards, code, image, video) in a visual editor with live preview.
No repository access required. Content is JSON, not code.

**Notebook playground** — Six pre-authored notebooks, one per topic, readable inline and runnable on
three compute targets.

**GPU without a GPU** — The platform host has no GPU. Heavy computer-vision topics (P&ID extraction,
corrosion segmentation) are routed to Google Colab or Kaggle. An injected stdlib-only bridge cell
streams logs, metrics and trained artifacts back into the run timeline:

```python
atlas.log("epoch 3 done")
atlas.metric(mean_iou=0.71)
path = atlas.dataset()          # pulls the dataset attached to this run
atlas.artifact("model.pt")      # uploads weights back to ATLAS
atlas.finish()
```

A notebook flagged `requires_gpu` can never silently run on the CPU worker — ATLAS re-routes it and
says so.

**Dataset and deck library** — Versioned uploads with automatic introspection: CSV/XLSX schema and
row counts, PPTX slide titles and bullets. Full history with uploader and timestamp, tagged by
pipeline stage (raw → cleaned → features → split → model).

**Graduation rubric** — The five web-app requirements are executable checks producing a 0–100
readiness score with fix hints. Verified: both starter templates score 100%, a Flask app scores 0%.

**One-click deployment** — Upload a zip, press deploy. ATLAS generates a Dockerfile, launches the
app, re-runs the rubric, and publishes it to the App Portal automatically.

---

## Architecture

```
backend/app/
  core/       config, database, security       (no business logic)
  domain/     SQLModel tables, enums, schemas  (no I/O)
  services/   runners/, compliance, deployments, assets, seed
  api/        routers + dependencies           (thin, no logic)
frontend/app/ Next.js App Router, static export
templates/    Streamlit and Gradio starters that pass all five rules
```

Compute runners implement one `Runner` protocol, so adding SageMaker or a local GPU box is a single
new class.

In production the Next.js static export is served by FastAPI itself — one process, one port, no CORS,
no reverse-proxy juggling.

---

## Configuration

Everything is environment-driven. Copy `.env.example` to `.env`.

| Variable | Purpose |
|---|---|
| `ATLAS_SECRET_KEY` | JWT signing key — change in production |
| `ATLAS_PUBLIC_BASE_URL` | Public URL. **Remote notebooks call back here** — the GPU bridge needs it |
| `ATLAS_DATABASE_URL` | Defaults to SQLite under `storage/`; accepts Postgres |
| `ATLAS_GITHUB_TOKEN`, `ATLAS_COLAB_GITHUB_REPO` | Enables true one-click Colab |
| `ATLAS_KAGGLE_USERNAME`, `ATLAS_KAGGLE_KEY` | Enables headless Kaggle GPU |
| `ATLAS_DEPLOY_DRIVER` | `local_process` (default), `coolify`, or `manifest` |
| `ATLAS_COOLIFY_*` | Base URL, token, project and server UUID |
| `ATLAS_GOOGLE_CLIENT_ID/SECRET` | Google SSO |

Without the Colab variables the bridge still works — it falls back to URL import.

---

## Deploy to Coolify

1. Push to Git.
2. Coolify → **New Resource → Application → Dockerfile**, repo root.
3. Port **8000**, persistent volume at **`/app/storage`**.
4. Set `ATLAS_SECRET_KEY` and `ATLAS_PUBLIC_BASE_URL`.
5. Deploy — `/api/health` gates the rollout.

---

## API

Interactive docs at `/api/docs`.

| Group | Endpoints |
|---|---|
| Auth | `POST /api/auth/login`, `/api/auth/google`, `GET /api/auth/me` |
| Content | `GET/POST /api/topics`, `GET /api/topics/{slug}`, `POST /api/topics/{id}/lessons`, `PUT /api/lessons/{id}` |
| Assets | `GET/POST /api/assets`, `GET /api/assets/{id}/download` |
| Playground | `GET /api/notebooks`, `POST /api/runs`, `GET /api/compute/targets` |
| Run bridge | `POST /api/runs/{id}/callback`, `GET /api/runs/{id}/dataset`, `POST /api/runs/{id}/artifact` |
| Deployment | `POST /api/deployments`, `/{id}/bundle`, `/{id}/check`, `/{id}/deploy`, `/{id}/dockerfile` |

---

## Docs

| Where | What |
|---|---|
| `/manual` (in the running app) | Illustrated user manual: 14 chapters, 16 real screenshots. No sign-in needed. |
| `tests/e2e.py` | 22 browser checks covering auth, curriculum, compute, rubric and the manual. |
| `tests/capture_manual.py` | Recaptures every manual screenshot from the running app. |

- `docs/PRD.md` — full product requirements, design rationale and verification log
- `docs/SYSTEM_DESIGN.md` — architecture, data model, sequence flows

---

## Troubleshooting

### Login succeeds, then bounces straight back to the login page

Almost always the browser is running a **stale or partial JavaScript bundle**,
so the page never becomes interactive and the sign-in form falls back to a plain
browser submit that throws the token away.

1. Hard-refresh: `Ctrl+Shift+R` (Windows/Linux) or `Cmd+Shift+R` (macOS).
2. Rebuild the UI so the served files match the code:
   ```bash
   python run.py --build
   ```
3. Open DevTools → Console. If you see 404s for `/_next/static/chunks/*.js`,
   the bundle on disk is out of date — the rebuild above fixes it.

Two other causes:

- **Blocked site storage** — private/incognito mode, a sandboxed `<iframe>`
  preview, or a strict cookie policy. ATLAS detects this and falls back to
  `sessionStorage`, then to in-memory storage, so sign-in still works; it shows
  a banner warning that the session ends on reload. Open ATLAS in a normal tab
  to stay signed in.
- **Clock skew.** JWTs carry an expiry; if the machine's clock is far off, every
  token looks expired. Sync the system time.

### "Cannot reach the ATLAS API"

The backend is not running or is on another port. Start it with `python run.py`
and confirm http://localhost:8000/api/health returns `{"status":"ok"}`.

### `python: command not found`

Use `python3 run.py`. On Windows, reinstall Python with **"Add Python to PATH"**
ticked.

### `ensurepip is not available` / venv creation fails

Debian and Ubuntu ship Python without the venv module:

```bash
sudo apt install python3-venv python3-pip
```

### No web interface, only JSON at `/`

Node.js was missing when the UI was built. Install Node 18+ from
[nodejs.org](https://nodejs.org), then:

```bash
python run.py --build
```

### Port 8000 already in use

```bash
python run.py --port 8080
```

### Reset everything

Delete `storage/atlas.db` and restart — the demo data is re-seeded on boot.
This erases uploaded datasets, runs and deployments.
