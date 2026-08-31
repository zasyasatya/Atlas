# ATLAS — Product Requirements Document

**Product:** ATLAS (Applied AI & Data Research Platform)

> Renamed from "AI Internship Operating System" on 2026-08-31. The programme mechanics in this
> document — intern/supervisor roles, cohorts, the graduation rubric — are unchanged: they are the
> product's onboarding and certification engine, and they still describe how deployments get graded.
**Version:** 1.0
**Date:** 29 August 2026
**Status:** Implemented — running reference build in this repository

---

## 1. Problem statement

An AI internship programme currently runs on scattered tooling: slides in shared drives, datasets
in chat threads, notebooks on personal laptops, and a review process that depends on the supervisor
remembering what "done" means. Three failures repeat every cohort:

1. **Content is locked behind engineers.** Only people who can open the codebase can add or edit
   learning material. A supervisor who wants to explain what a U-Net is has to file a ticket.
2. **Heavy topics stall on hardware.** Two of the six topics — P&ID extraction and corrosion
   segmentation — need a GPU to train anything real. The organisation has none.
3. **"Graduated" is a judgement call.** The five web-app requirements exist in a document, but
   nothing checks them, so reviews are inconsistent and interns discover gaps at the deadline.

ATLAS solves all three in one deployable application.

---

## 2. Goals and non-goals

### Goals

| # | Goal | Measure of success |
|---|---|---|
| G1 | Supervisors author AI-architecture content for non-experts without code access | A supervisor publishes a new topic with lessons in under 10 minutes, zero engineering involvement |
| G2 | Every topic has a runnable playground notebook | 6/6 topics ship with a guided notebook |
| G3 | Heavy CV training gets GPU time without owning a GPU | Topic 2 and 6 runs execute on Colab/Kaggle with metrics returned to the platform |
| G4 | Dataset and deck history is visible and versioned | Every upload shows uploader, version, timestamp, and schema preview |
| G5 | Graduation readiness is measured, not guessed | The 5 requirements are auto-checked and produce a 0–100 score |
| G6 | Deployment is one click and self-documenting | An intern goes from bundle upload to a live URL listed in the portal without leaving the app |
| G7 | The whole thing deploys to Coolify as one container | `docker build` → single image, one port, one volume |

### Non-goals

- Not a replacement for a real MLOps platform (no model registry, no feature store, no A/B serving).
- Not a general LMS — the content model is deliberately shaped around AI-architecture teaching.
- Not a GPU provider. ATLAS *brokers* free external GPU; it does not own hardware.
- No multi-tenancy. One organisation, one cohort pipeline, per deployment.

---

## 3. Users and permissions

| Role | Who | Can do |
|---|---|---|
| **Supervisor** | Programme owner, domain expert | Author topics/lessons/blocks, upload datasets and decks, create notebooks, review every app, run rubric checks |
| **Admin** | Platform owner | Everything a supervisor can, plus user and platform configuration |
| **Intern** | The learner | Consume curriculum, earn XP, run notebooks on any compute target, upload datasets, deploy apps |
| **Viewer** | Guest, external reviewer | Read-only access to curriculum and the app portal |

Authentication supports **local email + password (JWT)** and **Google SSO**, both configured by
environment variable. Demo accounts are seeded for immediate evaluation.

---

## 4. Functional requirements

### 4.1 Curriculum CMS (G1)

The core insight: **content is data, not code.** A lesson is an ordered list of typed blocks stored
as JSON. The supervisor composes lessons in a visual block editor with live preview.

Eight block types, chosen specifically for explaining AI architecture to a lay audience:

| Block | Purpose |
|---|---|
| `text` | Prose with lightweight markdown (`**bold**`, `*italic*`, `` `code` ``, bullets) |
| `callout` | Highlighted box in four tones — quest, warning, info, success |
| `architecture` | **Clickable pipeline diagram.** Each node reveals a plain-language note on tap. This is the primary tool for making an architecture legible to a beginner |
| `quiz` | Multiple choice with a mandatory explanation shown after answering |
| `flashcard` | Flip cards for jargon (baseline, ground truth, IoU…) |
| `code` | Syntax-styled snippet |
| `image` / `video` | Diagram or embed by URL |

**Game framing.** Every seeded topic follows a three-stage arc that maps learning to play:
*Stage 1 — Mission Briefing* (why this problem exists), *Stage 2 — Read the Blueprint* (the
architecture diagram), *Stage 3 — Boss Fight* (a quiz that punishes hand-waving). Completion awards
XP, XP drives levels, and levels feed a cohort leaderboard.

**Acceptance:** a supervisor with no repository access can create a topic, add three stages with
mixed block types, preview them, and publish — all from the browser.

### 4.2 Notebook playground (G2)

Each topic carries at least one notebook stored as nbformat v4 JSON in the database. Interns can
read it inline (rendered markdown, tables and syntax-highlighted cells), download the `.ipynb`, or
execute it on a chosen compute target.

Six notebooks ship pre-authored, matching the six topics.

### 4.3 Compute bridge (G3) — the load-bearing feature

The platform host has no GPU and never will. ATLAS therefore *borrows* compute through three
interchangeable runners behind one `Runner` protocol:

| Target | Mechanism | When to use |
|---|---|---|
| **Platform CPU** | `nbclient` in an isolated subprocess | Tabular, NLP, RAG — anything light. Instant, zero setup |
| **Google Colab GPU** | Notebook pushed to GitHub → one-click `Open in Colab`; falls back to signed URL import when GitHub is not configured | Free T4, learner-driven |
| **Kaggle GPU** | Kernel pushed headlessly through the Kaggle API | 30 GPU-hours/week, fully automatic — no browser tab |

**The ATLAS bridge.** Before dispatch, a generated cell is injected at the top of the notebook. It
is pure standard library, so it runs on a bare Colab or Kaggle runtime with no install step, and
gives the notebook five helpers:

```python
atlas.log("...")               # stream a line into the run timeline
atlas.metric(accuracy=0.94)    # push metrics to the dashboard
atlas.dataset()                # download the dataset attached to this run
atlas.artifact("model.pt")     # upload trained weights back to ATLAS
atlas.finish()                 # close the run
```

Authentication is a per-run bearer token, so a notebook can only write to its own run.

**GPU guard rail.** A notebook flagged `requires_gpu` can never silently execute on the CPU worker.
`resolve_target()` transparently re-routes the request to the topic's GPU target and the UI tells
the learner it happened. This is what makes topics 2 and 6 workable.

### 4.4 Datasets, decks and history (G4)

One versioned asset store handles four kinds: `dataset`, `deck`, `artifact`, `image`.

- **Automatic introspection on upload.** CSV/XLSX yield column names, row/column counts and a
  12-row preview. PPTX yields slide count plus per-slide titles and bullets, so an intern can skim
  the preparation deck without downloading it.
- **Versioning.** Re-uploading the same title under the same topic increments the version; history
  stays visible with uploader and timestamp.
- **Pipeline stage tagging** — raw → cleaned → features → split → model — so the dataset lineage for
  each topic is legible at a glance.
- Artifacts produced by remote GPU runs land here automatically via `atlas.artifact()`.

### 4.5 Graduation rubric (G5)

The five requirements are encoded as executable rules that statically analyse the uploaded bundle.

| Rule | Requirement | How it is checked |
|---|---|---|
| **R1** | Framework must be Streamlit or Gradio | Detects the import/usage and cross-checks it against the declared framework |
| **R2** | Input form: single entry **and** bulk spreadsheet upload | Requires both per-field widgets and a file uploader accepting `.csv`/`.xlsx` |
| **R3** | Documentation page: limitations, dataset, architecture, evaluation | All four sections must be present; the failure message names the missing ones |
| **R4** | Output: confidence score (classification) or MAPE (forecasting), plus a chart | Metric requirement switches on the topic's `task_type`; chart detection is separate |
| **R5** | Deployed URL attached in Whimsical | Validates a Whimsical link is recorded on the deployment |

Result: a 0–100 readiness score (a `warn` counts half), with actionable fix hints on every failure.
Verified behaviour: both starter templates score **100%**; a Flask app with no docs scores **0%**.

### 4.6 One-click deployment (G6)

Upload a `.zip` (or a bare `app.py`), press deploy. ATLAS then:

1. Unpacks the bundle safely (path-traversal guarded) and auto-detects the entrypoint.
2. Generates `requirements.txt` if missing and always writes a **Dockerfile** and
   `docker-compose.yml` tuned to the framework — including the correct Streamlit/Gradio start
   command and health check.
3. Executes through the configured driver:
   - `local_process` — isolated virtualenv on an allocated port (default; ideal for demos)
   - `coolify` — creates and deploys the application through the Coolify API
   - `manifest` — writes artifacts only, for air-gapped review
4. Re-runs the rubric and, on success, **publishes to the App Portal automatically**.

Two reference starters are downloadable in-app; both pass all five rules out of the box and are
meant to be edited rather than read.

### 4.7 App portal

Every deployed app in one place with framework, owner, topic, live URL, Whimsical link, per-rule
badges and readiness score. This is the supervisor's review surface and the cohort's shared record.

---

## 5. Non-functional requirements

| Area | Requirement | Implementation |
|---|---|---|
| **Architecture** | Monolith, easy to manage | FastAPI serves the Next.js static export from the same process and port |
| **Code quality** | Clean architecture | Layered `core / domain / services / api`; runners behind a `Protocol`; no business logic in routers |
| **Portability** | Deployable to Coolify | Multi-stage Dockerfile → single image, port 8000, one volume at `/app/storage` |
| **Configuration** | No code changes between environments | Everything via `ATLAS_*` environment variables with sane defaults |
| **Security** | Least privilege | JWT auth, PBKDF2-SHA256 (240k rounds), role guards, per-run callback tokens, non-root container user, zip-slip protection |
| **Data** | Zero-setup start, production path available | SQLite by default; `ATLAS_DATABASE_URL` switches to Postgres |
| **Accessibility** | Usable on a phone | Verified no horizontal overflow at 390 px across all pages |

---

## 6. Design system

Derived from the two supplied references: the editorial portfolio (typography, restraint, engineering
grid, dot-matrix motif) and the SaaS dashboard (persistent sidebar, stat cards, data density).

- **Typeface:** Plus Jakarta Sans, self-hosted as a variable WOFF2 (27 KB) so the UI renders
  identically offline and inside sandboxed previews.
- **Palette:** paper `#F6F8F6`, ink `#12160F`, sage `#5B8C6E` as the single accent, plus four
  semantic signal colours. Low-chroma and calm by intent — the data should be the loudest thing.
- **Type scale:** tight negative tracking on display sizes (`-0.035em`), uppercase eyebrow labels at
  `0.16em`, generous 1.7 line height for body copy.
- **Surfaces:** 14–20 px radii, hairline `#E2E8E2` borders, two-layer soft shadows, and the faint
  28 px engineering grid behind every page header.
- **Motion:** one `rise` entrance easing and a slow pulse for live status. Nothing decorative.

---

## 7. Data model

```
User ──< Progress >── Lesson >── Topic
                         │         ├──< Notebook ──< Run ──< (metrics, logs, artifacts)
                         │         ├──< Asset      (dataset | deck | artifact | image)
                         └─< LessonBlock           └──< Deployment ──< ComplianceCheck
ActivityLog  (cross-cutting audit trail)
```

Notebook documents and lesson block payloads are stored as JSON text, keeping the schema stable
while content evolves.

---

## 8. Verification performed

| Test | Result |
|---|---|
| Notebook validity (all 6, nbformat) | Pass |
| CPU run end-to-end | **Succeeded in 3.5 s**, metrics returned (`accuracy 0.9417`), 2 artifacts auto-uploaded |
| GPU auto-upgrade for heavy topics | Requested `local_cpu` → routed to `colab_gpu`, Colab URL issued |
| Rubric — Streamlit starter | 100% (5/5) |
| Rubric — Gradio starter | 100% (5/5) |
| Rubric — negative control (Flask, no docs) | 0% (0/5) |
| One-click deploy | Live Streamlit app, `/_stcore/health` → 200, auto-published to portal |
| Production static export | 12 pages, no errors |
| Monolith serving | All routes 200, `/api/*` 404s correctly instead of falling through |
| Container layout simulation | Boots, seeds, resolves templates and static dir |
| Browser E2E (Playwright) | **14/14 checks, zero console errors** |
| Mobile 390 px | No horizontal overflow on any page |

A genuine bug was caught and fixed during validation: `mkdir -p /app/storage/{a,b}` silently creates
a directory literally named `{a,b}` under dash (the shell in `python:3.11-slim`). Replaced with an
explicit loop and verified both the failure and the fix.

---

## 9. Deployment to Coolify

1. Push this repository to Git.
2. In Coolify: **New Resource → Application → Dockerfile**, point at the repo root.
3. Expose port **8000**; add a persistent volume at **`/app/storage`**.
4. Set environment variables (see `.env.example`). At minimum:
   - `ATLAS_SECRET_KEY` — long random string
   - `ATLAS_PUBLIC_BASE_URL` — the public URL; **remote notebooks call back to this address**, so
     the Colab/Kaggle bridge does not work until it is correct.
5. Deploy. The health check at `/api/health` gates the rollout.

For GPU bridging add `ATLAS_GITHUB_TOKEN` + `ATLAS_COLAB_GITHUB_REPO` (Colab) and/or
`ATLAS_KAGGLE_USERNAME` + `ATLAS_KAGGLE_KEY` (Kaggle). To have ATLAS deploy intern apps into Coolify
itself, set `ATLAS_DEPLOY_DRIVER=coolify` plus the four Coolify variables.

---

## 10. Future work

- Real-time run streaming over WebSocket instead of 4-second polling.
- Postgres migration path with Alembic (the SQLModel schema is already compatible).
- Notebook diffing and per-intern forks.
- Rubric extension: optional AST-based analysis for stricter R2/R4 detection.
- Cohort analytics: time-to-completion per stage, drop-off detection.
