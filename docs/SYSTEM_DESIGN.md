# ATLAS — System Design

Companion to `PRD.md`. This document covers how the system is built rather than what it must do.

---

## 1. Deployment topology

```
                            ┌──────────────────────────────────────┐
  browser ───── :8000 ────► │  ATLAS container (single image)      │
                            │                                      │
                            │  uvicorn → FastAPI                   │
                            │    ├── /api/*   JSON API             │
                            │    └── /*       Next.js static export│
                            │                                      │
                            │  /app/storage   (mounted volume)     │
                            │    datasets/ decks/ artifacts/       │
                            │    notebooks/ deployments/ runs/     │
                            │    atlas.db                          │
                            └───────────┬──────────────────────────┘
                                        │ outbound only
                     ┌──────────────────┼───────────────────┐
                     ▼                  ▼                   ▼
              GitHub Contents      Colab runtime       Kaggle Kernels
              (notebook sync)      (T4, learner)       (T4/P100, headless)
                                        │                   │
                                        └─── callbacks ─────┘
                                          POST /api/runs/{id}/callback
                                          GET  /api/runs/{id}/dataset
                                          POST /api/runs/{id}/artifact
```

One process, one port. No CORS in production because the frontend is served from the same origin.
All external compute is *outbound-initiated by the notebook*, so ATLAS needs no inbound firewall
exceptions beyond its own HTTPS port — but it **must** be publicly reachable at
`ATLAS_PUBLIC_BASE_URL` for callbacks to land.

---

## 2. Layering

```
api/          routers, dependencies          thin — parse, authorise, delegate
   ↓
services/     runs, compliance, deployments, assets, activity, seed, notebook_factory
   ↓          corrosion_notebooks (the five-stage Topic 6 playground)
   ↓          runners/  base · local_cpu · colab_gpu · kaggle_gpu · bridge
domain/       models (SQLModel), schemas (Pydantic), enums        no I/O
   ↓
core/         config, db, security                                no business logic
```

Rules enforced throughout:

- Routers never contain business logic. They call a service and shape a response.
- Domain objects have no I/O. Serialisation lives in `schemas.py`.
- Services never import from `api/`. Dependencies point one direction only.
- Every compute target implements the same `Runner` protocol, so the orchestrator
  (`services/runs.py`) is agnostic to where the work actually happens.

---

## 3. Data model

```sql
users(id, email, full_name, hashed_password, google_sub, role, cohort, ...)

topics(id, slug, title, subtitle, summary, difficulty, accent, icon,
       heavy_compute, task_type, xp_reward, order_index, status)
  └─ lessons(id, topic_id, slug, title, hook, duration_minutes, xp_reward, order_index)
       └─ lesson_blocks(id, lesson_id, order_index, block_type, payload_json)

progress(id, user_id, lesson_id, topic_id, completed, score, xp_earned)

assets(id, topic_id, kind, title, filename, stored_path, size_bytes, checksum,
       version, row_count, column_count, slide_count, preview_json, stage, uploaded_by)

notebooks(id, topic_id, slug, title, default_target, requires_gpu, content_json, version)
  └─ runs(id, notebook_id, topic_id, user_id, target, status, dataset_asset_id,
          metrics_json, logs, callback_token, external_url, duration_seconds)

deployments(id, topic_id, user_id, name, slug, framework, entrypoint, bundle_path,
            status, url, internal_port, process_pid, whimsical_url, readiness_score,
            published_to_portal)
  └─ compliance_checks(id, deployment_id, rule_id, label, status, detail)

activity_logs(id, user_id, actor_name, action, entity_type, entity_id, topic_id, detail)
```

**Why JSON columns.** `lesson_blocks.payload_json` and `notebooks.content_json` hold free-form
documents. Block schemas evolve constantly during a programme; notebooks are nbformat documents that
should stay untouched. Storing them as text keeps the relational schema stable and avoids a
migration every time a supervisor wants a new block variant.

**`task_type` drives the rubric.** A `forecasting` topic requires MAPE; a `classification` topic
requires a confidence score. One field on the topic decides which R4 branch runs.

---

## 4. The compute bridge

### 4.1 Dispatch sequence

```
intern              ATLAS                     GitHub / Kaggle        Colab / Kaggle runtime
  │                   │                             │                        │
  ├─ POST /api/runs ─►│                             │                        │
  │                   ├ resolve_target()            │                        │
  │                   │   requires_gpu && cpu?      │                        │
  │                   │   → upgrade to GPU target   │                        │
  │                   ├ create Run + callback_token │                        │
  │                   ├ inject bridge cell          │                        │
  │                   ├──── push notebook ─────────►│                        │
  │◄── url + steps ───┤                             │                        │
  │                                                 │                        │
  ├──────────── open link, Run all ─────────────────┼───────────────────────►│
  │                   │                             │                        │
  │                   │◄──── POST /callback (logs, metrics) ─────────────────┤
  │                   │◄──── GET  /dataset?token= ───────────────────────────┤
  │                   │◄──── POST /artifact?token= ──────────────────────────┤
  │◄── live timeline ─┤                                                      │
```

### 4.2 Runner selection

| Runner | Execution | Failure mode handled |
|---|---|---|
| `LocalCpuRunner` | Subprocess running `nbclient` | 20-minute timeout; kernel crash captured as run error |
| `ColabRunner` | GitHub push → Colab URL; falls back to signed URL import | GitHub unconfigured or push fails → automatic fallback, never blocks the learner |
| `KaggleRunner` | `POST /kernels/push` with `enable_gpu` | Missing credentials returns actionable setup instructions rather than an error |

**Why the CPU runner uses a subprocess.** `nbclient` installs asyncio signal handlers, which raises
`ValueError: add_signal_handler() can only be called from the main thread` when executed inside a
worker thread. This was hit during development and fixed by isolating execution in
`_exec_notebook.py`, which also means a runaway notebook can be killed without touching the API
process.

**Why the bridge is stdlib-only.** Colab and Kaggle runtimes are ephemeral and vary. Using only
`urllib` and `json` means the bridge cell runs before any `pip install` and cannot break on a
dependency conflict. Callback failures are caught and printed — a network hiccup must never crash a
20-minute training run.

**Security.** Each run gets a `callback_token`. The dataset, artifact and callback endpoints
authenticate against that token alone, so a notebook can read and write only its own run and never
needs the user's JWT — which would otherwise end up pasted in a shared Colab tab.

### 4.3 A topic that is a pipeline

Corrosion segmentation ships five notebooks instead of one — preprocessing/EDA, training,
evaluation, inference, deployment — generated by `services/corrosion_notebooks.py`. They share one
bootstrap cell that has to make the same file work in three environments:

| Environment | What the bootstrap supplies |
|---|---|
| ATLAS run | Nothing: the injected bridge is already there, so `atlas.*` streams to the run timeline |
| Local Jupyter | A stand-in `atlas` object, and dataset discovery that walks up the directory tree |
| Plain Colab | Drive mounted as the work folder, the dataset cached there, a keepalive |

The library the notebooks import (`templates/corrosion_unet/corrosion_kit.py`) is a real,
independently tested file, embedded into each notebook at build time and written to disk by the
bootstrap. Embedding rather than importing from the server is what lets a notebook run on a Colab
that cannot reach this instance; keeping one source file is what stops five notebooks and a
deployed app from drifting apart.

**State between stages** lives in the work folder, not in the kernel: a manifest from stage 1,
checkpoints from stage 2, a report from stage 3. That is what makes the pipeline restartable at any
point — and it is the same mechanism that survives a Colab disconnect, because on Colab the work
folder is Drive. The training loop writes a checkpoint with optimiser and scheduler state every
epoch through `save_checkpoint`, which writes a temp file and renames it: a runtime killed
mid-write leaves the previous checkpoint intact rather than a truncated one. Re-running the cell
resumes from the recorded epoch, and a configurable time budget ends the loop cleanly before
Colab's ceiling does.

---

## 5. Compliance engine

`services/compliance.py` walks the uploaded bundle, concatenates all text-like files under 2 MB,
and applies compiled regex rules.

```
bundle → collect text → 5 rules → ComplianceCheck rows → readiness_score
                                     pass = 1.0
                                     warn = 0.5   (e.g. metric present but no chart)
                                     fail = 0.0
```

R4 branches on the topic's `task_type`: forecasting and regression demand MAPE, everything else
demands a confidence score. Failures carry the rule's fix hint, so the message an intern sees is
"Missing bulk spreadsheet upload. Fix: add per-field widgets AND a file uploader accepting
.csv/.xlsx" rather than a bare red cross.

Static analysis is deliberate: it runs in milliseconds, needs no sandbox, and cannot be defeated
accidentally. It *can* be defeated deliberately (a comment mentioning "MAPE" would pass R4), which is
acceptable — the rubric is a safety net for honest mistakes, with a human supervisor as the final
gate.

---

## 6. Deployment engine

```
upload bundle
   → unpack (zip-slip guarded, single-root flattened)
   → detect entrypoint (declared → app.py/main.py/streamlit_app.py → first .py)
   → ensure requirements.txt (framework baseline merged in if absent)
   → generate Dockerfile + docker-compose.yml + .dockerignore
   → driver:
       local_process → venv, pip install, spawn on allocated port (own process group)
       coolify       → POST /api/v1/applications/dockercompose
       manifest      → stop here
   → re-run rubric → publish to portal
```

Ports are allocated from a configurable range and tracked on the deployment row. Processes are
spawned in their own process group so `stop` can terminate the whole tree — a session on POSIX, a
`CREATE_NEW_PROCESS_GROUP` job on Windows, where `taskkill /T` does the killing. Stopping waits for
the process to actually be gone: a redeploy starts its replacement within milliseconds, and an old
Streamlit still holding the port fails the new one while the database happily records RUNNING.

`local_process` shares the platform's own site-packages with each deployment through a `.pth` file
(`ATLAS_DEPLOY_SYSTEM_SITE_PACKAGES`, default on). A computer-vision bundle asks for torch, and
downloading 2.5 GB per deployment onto a teaching laptop is the difference between a deploy that
works and one that dies out of disk. `venv --system-site-packages` does not achieve this: it shares
the *base* interpreter's packages, and ATLAS runs from a virtualenv of its own.

The generated Dockerfile is the same artifact regardless of driver — what runs locally is what
Coolify builds, which removes the classic "works on the demo server" gap.

---

## 7. Frontend

Next.js 14 App Router, exported statically (`output: 'export'`) and served by FastAPI.

- **Dev:** `next dev` with a rewrite proxying `/api/*` to `:8000`.
- **Prod:** static HTML/JS in `backend/app/static`, served by a catch-all route that resolves
  `path` → `path.html` → `path/index.html` → `index.html`, while `/api/*` correctly 404s instead of
  falling through to the SPA.

Dynamic routes are avoided because static export requires `generateStaticParams`, which cannot know
about topics created at runtime. The topic page is therefore `/curriculum/view?slug=…` — a static
page reading a query parameter.

State is deliberately simple: `fetch` + `useState`, a thin `api` client handling auth headers and
401 redirects, and polling (4 s) only while a run is in flight. No global store, no data-fetching
library — the app has fewer than a dozen screens and the complexity would not pay for itself.

Fonts are self-hosted as a variable WOFF2 so the UI is identical offline and inside sandboxed
preview iframes with no network access.

---

## 8. Security posture

| Concern | Mitigation |
|---|---|
| Password storage | PBKDF2-SHA256, 240,000 rounds, per-user salt, constant-time compare |
| Session | JWT (HS256), 7-day expiry, verified on every request |
| Authorisation | Role guards as FastAPI dependencies; `EditorUser` gates all authoring routes |
| Notebook callbacks | Per-run opaque token; no user JWT ever leaves the platform |
| Zip extraction | Absolute paths and `..` members skipped |
| Upload size | 200 MB cap enforced before write |
| Container | Non-root user (uid 10001), tini as PID 1 |
| Secrets | Environment only; never persisted to the database or logs |

**Known limitation.** The `local_process` deploy driver executes intern-supplied Python on the host.
This is appropriate for a trusted internal cohort and convenient for demos, but for untrusted code
use `ATLAS_DEPLOY_DRIVER=coolify`, which builds and runs each app in its own container.

---

## 9. Performance characteristics

| Operation | Measured |
|---|---|
| API cold start (incl. seed) | ~1.5 s |
| Page load (static, first paint) | 87 KB shared JS + 1–8 KB per route |
| CPU notebook run (tabular, 1,200 rows) | 3.5 s end to end including metric callbacks |
| One-click deploy (Streamlit, cold venv) | ~32 s including dependency install |
| Rubric evaluation | < 100 ms |

---

## 10. Extension points

- **New compute target** — implement `Runner.launch()`, register in `_RUNNERS`. Nothing else changes.
- **New block type** — add to the `LessonBlockType` enum, a renderer case, and a form case. The
  storage layer needs no migration.
- **New rubric rule** — append to `RULES` and add its branch in `evaluate()`. The score normalises
  automatically.
- **Postgres** — set `ATLAS_DATABASE_URL`. The SQLModel schema is already compatible; add Alembic
  when the first destructive migration is needed.
