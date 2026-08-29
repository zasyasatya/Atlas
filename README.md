# ATLAS — AI Internship Operating System

End-to-end platform for running an AI internship programme: author curriculum without code, run
notebooks on borrowed GPUs, manage datasets, and ship graded Streamlit/Gradio apps.

FastAPI + Next.js monolith. One image, one port, deployable to Coolify.

---

## Quick start

```bash
# 1. backend
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --reload --port 8000

# 2. frontend (separate terminal, dev mode proxies /api to :8000)
cd frontend
npm install
npm run dev            # http://localhost:3000
```

Or run the whole thing as one container:

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

- `docs/PRD.md` — full product requirements, design rationale and verification log
- `docs/SYSTEM_DESIGN.md` — architecture, data model, sequence flows
