# ATLAS — Applied AI & Data Research Platform

End-to-end platform for applied AI and data work: author curriculum without code, run notebooks on
borrowed GPUs, manage datasets, and ship Streamlit/Gradio apps that are live on your own domain the
second they start.

FastAPI + Next.js monolith. One image, one port, deployable to Coolify.

> The name and tagline are configuration, not constants: `ATLAS_APP_NAME`, `ATLAS_APP_TAGLINE`,
> `ATLAS_APP_TAGLINE_SHORT` and `ATLAS_APP_SUBTITLE` retitle the tab, the sign-in screen, the
> sidebar, the CLI banner and the manual footer — for a programme, a client, a pilot — without
> rebuilding the frontend. See [Branding](#branding--white-labelling).

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

All runtime data — the SQLite database, uploaded datasets/decks, runs and
deployed bundles — is persisted on the host under the repository's **`./data`**
directory, which is bind-mounted onto `/app/storage` inside the container.
That makes the data a plain, portable folder you can inspect, back up, or
`git`-ignore by design. Deleting `./data` resets the install; removing the
volume line from `docker-compose.yml` swaps back to an anonymous volume.

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

**Notebook playground** — Ten pre-authored notebooks, readable inline and runnable on three compute
targets. Five topics get one notebook each; corrosion segmentation gets the full pipeline as five —
preprocessing/EDA, training, evaluation, inference and deployment — so nobody re-runs training to
look at a prediction.

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

**No per-app ports — apps live under virtual directories that work immediately.**
Deployed apps are not separate public services. Each runs on an internal port and
is served as a path on the main domain — `https://yourdomain.com/app/<slug>` — so
one domain and one port carry everything.

**ATLAS is the proxy.** The platform answers `/<prefix>/<slug>/` itself and
forwards it — HTTP *and* WebSocket, streaming both ways — to the app's internal
port. A deployed app opens in a new tab the moment its process is listening:
nothing to install, nothing to copy, nothing to reload, no firewall rule, and the
same relative link works on a domain, a LAN IP, `localhost:8000` or a
port-addressed preview host. App URLs are stored origin-relative (`/app/my-app/`)
for exactly that reason, so they never go stale when the host changes.

That also removes the failure mode the old flow had, where a deploy "succeeded"
while its link 404'd because no nginx config had been installed yet: a link that
goes to the portal's own HTML is worse than a slow deploy.

**nginx stays optional** — for TLS, rate limits, or serving the bundle from
another host. When you do use it, ATLAS keeps it in sync on every deploy, stop and
delete:

* one managed snippet per app, `atlas-app-<slug>.conf`, is written to a
  dedicated `apps.d` directory (only ATLAS-managed `atlas-app-*.conf` files are
  ever touched, so every other site/app on the nginx host is left alone);
* a full `atlas.conf` vhost is also generated that serves the apps **and**
  proxies the portal/API to the backend — one server block powers the whole
  platform on ports 80/443;
* nginx is validated (`nginx -t`) before reload and the change is **rolled back
  if invalid**, so a broken app can never take the proxy (or the other apps)
  down; the reload is graceful, so in-flight requests are not dropped.

Point `ATLAS_NGINX_CONF_DIR` / `ATLAS_NGINX_RELOAD_CMD` at a live nginx for
automatic reloads, or set `ATLAS_NGINX_AUTO_INSTALL=true` and ATLAS will also
install the vhost into `sites-available` + `sites-enabled` (or `conf.d`) for you —
writing only its own `atlas.conf`, refusing to overwrite a file it does not own,
and rolling back if `nginx -t` rejects the result. Without nginx the generated
files still land under `storage/nginx/` for review or download from
**Portal → App routing**, or via `GET /api/deployments/proxy-config` /
`/proxy-status`.

`GET /api/deployments/proxy-status` answers the two questions users actually
ask, separately: is the path routed, and is the app answering on its port?
`POST /api/deployments/proxy-sync` re-runs routing without a redeploy, which is
what a failed reload needs. The path prefix defaults to `app` and can be changed
with `ATLAS_DEPLOY_URL_PREFIX`; `ATLAS_DEPLOY_BUILTIN_PROXY=false` hands the path
back to your own proxy.

**Per-app persistent, isolated data.** Each deployed app gets its own data folder
under `storage/appdata/<id>_<slug>/` — outside the bundle, so it survives bundle
re-uploads and redeploys, and is separate from every other app. The app's
`HOME`, XDG cache/config/data dirs, temp dir and common ML caches (Hugging Face,
Torch, Matplotlib, Gradio) are all pinned inside it, so apps cannot read or
overwrite each other's files and nothing is lost on redeploy. It lives on the
same persistent volume (`./data` → `/app/storage`); the generated Docker
compose mounts an isolated `app-data` volume at `/data` for container deploys.

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
| `ATLAS_ENVIRONMENT` | `development` or `production`. Controls the public/operator split below. Anything unrecognised is treated as production |
| `ATLAS_SECRET_KEY` | JWT signing key — change in production |
| `ATLAS_PUBLIC_BASE_URL` | Public URL. **Remote notebooks call back here** — the GPU bridge needs it |
| `ATLAS_DATABASE_URL` | Defaults to SQLite under `storage/`; accepts Postgres |
| `ATLAS_GITHUB_TOKEN`, `ATLAS_COLAB_GITHUB_REPO` | Enables true one-click Colab |
| `ATLAS_KAGGLE_USERNAME`, `ATLAS_KAGGLE_KEY` | Enables headless Kaggle GPU |
| `ATLAS_DEPLOY_DRIVER` | `local_process` (default), `coolify`, or `manifest` |
| `ATLAS_DEPLOY_URL_PREFIX` | Virtual-directory prefix (default `app`) → `/app/<slug>` |
| `ATLAS_DEPLOY_BUILTIN_PROXY` | `true` (default): ATLAS serves each app's path itself — no proxy to install |
| `ATLAS_DEPLOY_ROUTE_TTL_SECONDS` | How long a slug→port route is cached (default 2s) |
| `ATLAS_NGINX_CONF_DIR`, `ATLAS_NGINX_VHOST_FILE` | Where ATLAS writes per-app snippets + the vhost for automatic nginx sync |
| `ATLAS_NGINX_AUTO_INSTALL` | Also install the vhost into sites-available/conf.d (opt-in; nothing needs it) |
| `ATLAS_NGINX_RELOAD_CMD`, `ATLAS_NGINX_AUTO_RELOAD` | Command to reload nginx and whether to do it automatically |
| `ATLAS_APP_NAME`, `ATLAS_APP_TAGLINE` | Public identity: name + what the product is called underneath it |
| `ATLAS_APP_TAGLINE_SHORT`, `ATLAS_APP_SUBTITLE` | Sidebar/sign-in label, and the sentence on the sign-in screen |
| `ATLAS_DEPLOY_SYSTEM_SITE_PACKAGES` | `local_process` only. Default `true`: a deployed app shares the platform's installed packages instead of pulling its own 2.5 GB of torch |
| `ATLAS_COOLIFY_*` | Base URL, token, project and server UUID |
| `ATLAS_GOOGLE_CLIENT_ID/SECRET` | Google SSO |

Without the Colab variables the bridge still works — it falls back to URL import.

---

## Branding & white-labelling

Four variables decide what the product is called. The server owns them and the UI
reads them from `GET /api/config`, which is why they are not compiled into the
bundle:

```bash
ATLAS_APP_NAME=NUSANTARA-AI
ATLAS_APP_TAGLINE=Applied AI & Data Research Platform
ATLAS_APP_TAGLINE_SHORT=Programme Console
ATLAS_APP_SUBTITLE=From first notebook to deployed app, with the rubric to prove it.
ATLAS_DOCS_URL=https://docs.your-programme.com   # optional; empty = built-in /manual
```

They reach the browser tab title, the sign-in card, the sidebar wordmark, the
`run.py` banner, the manual footer, the FastAPI/OpenAPI description and every
generated proxy config header. The frontend ships fallback strings for the same
values so nothing flashes or reflows before the first response, and
`tests/branding.py` fails if a fallback and the server default ever disagree —
the usual way a rename ends up half-applied.

Deliberately **not** renamed by those variables: the domain vocabulary inside the
product (`intern`, `supervisor`, `cohort`, graduation rubric). Those are role and
workflow names, they are stored in the database, and a cosmetic rename would break
existing content for no user gain.

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
| Users | `GET/POST /api/users`, `PATCH /api/users/{id}` (admin/supervisor only) |
| Playground | `GET /api/notebooks`, `POST /api/runs`, `GET /api/compute/targets` |
| Run bridge | `POST /api/runs/{id}/callback`, `GET /api/runs/{id}/dataset`, `POST /api/runs/{id}/artifact` |
| Deployment | `POST /api/deployments`, `/{id}/bundle`, `/{id}/check`, `/{id}/deploy`, `/{id}/dockerfile` |

---

## Development vs production

The same build serves two audiences. `ATLAS_ENVIRONMENT` decides which one.

| | `development` (default for `python run.py`) | `production` (default in Docker/Coolify) |
|---|---|---|
| Manual chapters | 16 — everything | 12 — end-user content only |
| Getting started / Settings / Troubleshooting | Shown | Hidden |
| Demo account cards on the sign-in page | Shown, form prefilled | Hidden, form empty |
| `GET /api/auth/demo-accounts` | `200` with credentials | `404` |
| Env-var tables and callback-URL setup notes | Shown | Hidden |
| Topics an intern can see | All of them | **Only the ones a supervisor assigned** |

Interns and instructors on a deployed instance see only what they need: how to sign
in, learn, run notebooks, upload data and ship an app. Instructions for installing
and operating the platform stay on the operator's machine.

### Notebooks refresh themselves

Playground notebooks are generated from `notebook_factory`, so they are part of
the build rather than user content. An install created before a lesson was
rewritten used to keep serving the notebook it was seeded with - which is how a
playground ends up showing 13 cells when the current material has 24. On every
startup ATLAS now regenerates any shipped notebook whose content has drifted,
matched by its seeded slug. Notebooks an author created or renamed through the
CMS are left alone, and progress, runs and assignments are never touched.

The same pass installs notebooks a build ships that the install has never seen —
which is how the corrosion topic went from one notebook to five without anyone
resetting a database. A notebook a build no longer ships is deleted if nothing
points at it, and retitled *Superseded* if a run does: taking someone's history
with it would be worse, and leaving it unlabelled beside its replacements is
worse still.

### People & accounts

Admins and supervisors manage who can sign in from **Users** (sidebar). From
there you can list every account, add a new one (email, name, password, role
and optional cohort), and enable/disable access — useful for creating intern
and supervisor accounts up front or revoking a leaver's access.

API: `GET/POST /api/users`, `PATCH /api/users/{id}`. Creating accounts is
guarded the same way content is: anyone with an `admin` or `supervisor` role
may add interns and viewers, but only an admin can create or promote other
admins/supervisors, and no one can edit an account more privileged than their
own.

### Topic assignments

On a production instance an intern sees only the topics a supervisor has ticked for
them. That covers the topic list, the topic page, its notebook, its `.ipynb` export,
its datasets and its reference pipeline - a guessed URL returns `404`, not `403`, so
the shape of the curriculum is not leaked to someone who is not enrolled in it.
Supervisors, admins and viewers are never restricted.

Supervisors manage this from **Curriculum -> Topic assignments**: a grid of interns
against topics, one click per grant. The seeded demo intern starts with three topics
so the gate is visible without looking broken.

Development stays wide open on purpose - a fresh install should be explorable before
anyone has wired up a single assignment.

The switch is **fail-closed**: only `development`, `dev`, `local`, `test` and
`testing` unlock the operator content. A typo, an empty value or `staging` all
resolve to production, so a misconfigured deployment hides too much rather than
leaking credentials. The browser also assumes production until `/api/config`
answers, so operator content never flashes on screen during load.

```bash
python run.py                                  # development
ATLAS_ENVIRONMENT=production python run.py     # what a deployment looks like
```

Hiding the demo endpoint does not disable the accounts — it only stops handing
passwords to anonymous callers. Set `ATLAS_SEED_DEMO_DATA=false` before a real
cohort, or change every password.

---

## Docs

| Where | What |
|---|---|
| `/manual` (in the running app) | Illustrated user manual. 16 chapters in development, 12 in production. No sign-in needed. |
| `tests/e2e.py` | 22 browser checks covering auth, curriculum, compute, rubric and the manual. |
| `tests/prod_mode.py` | 26 checks that production really hides the operator content. Needs a dev **and** a prod instance. |
| `tests/lesson_contract.py` | 13 checks that every seeded lesson block matches what `BlockRenderer.tsx` reads. Catches blocks that would render blank. |
| `tests/google_auth.py` | 31 checks on Google id_token verification: forged signatures, `alg=none`, algorithm confusion, wrong audience, expiry, unverified email, nonce replay, PKCE. No network needed. |
| `tests/google_flow.py` | 23 checks driving a full sign-in against a stand-in Google: authorize, code exchange, callback, session, and replay rejection. |
| `tests/proxy_isolation.py` | Checks that each app is rendered as its own nginx virtual directory, sync writes/removes only ATLAS-managed snippets, the optional vhost install never touches a file it does not own, and every app's data/cache/temp paths are isolated in a persistent per-app folder. No server or nginx needed. |
| `tests/virtual_directory.py` | Drives the built-in proxy against a real app process: path and query passthrough, streamed POST bodies, `Host`/`Origin` preserved, hop-by-hop headers dropped, prefix-relative redirects, the readable pages for stopped/unknown apps, and a live WebSocket echo through the bridge. |
| `tests/deploy_seamless.py` | The end-to-end claim: boots a real server, deploys a real bundle through the normal API, then fetches `/app/<slug>/` on the portal's own port and checks the app answered — plus the stop and delete paths. No nginx, no network. |
| `tests/branding.py` | Verifies the brand has one owner: server defaults and the frontend fallbacks agree, `/api/config` publishes them, and no `Internship OS`-era string survived anywhere else. |
| `tests/assignments.py` | 34 checks that assignment gating holds on every topic-scoped route, and that the pipeline library serves files without path traversal. Needs a dev **and** a prod instance. |
| `tests/course_e2e.py` | 37 checks driving one whole internship course through the API: lessons, all five corrosion notebooks, checkpoint upload, bundle, rubric, deploy, portal, and an HTTP fetch of the running app. Needs a dev instance and a trained checkpoint. |
| `tests/capture_manual.py` | Recaptures every manual screenshot from the running app. |

### Topic 6: the corrosion pipeline

The playground for corrosion segmentation is **five notebooks**, run left to
right. Each writes into one work folder that the next one reads.

| Notebook | What it does | Default target |
|---|---|---|
| `corrosion-1-eda` | finds the dataset, decides what the mask values mean, measures the imbalance, writes `manifest.json` | Platform CPU |
| `corrosion-2-training` | trains the U-Net, checkpointing every epoch | Colab GPU |
| `corrosion-3-evaluation` | per-class IoU on the test split, confusion matrix, worst predictions | Colab GPU |
| `corrosion-4-inference` | segments new photographs, single and bulk, with confidence maps | Platform CPU |
| `corrosion-5-deployment` | assembles the app bundle, self-checks the rubric, ships it | Platform CPU |

They run unchanged in three places. Dispatched from ATLAS, the injected bridge
streams metrics into the run timeline. Downloaded into local Jupyter or opened
straight in Colab, the bootstrap cell supplies a stand-in for that bridge and
finds the dataset by walking up the directory tree.

**Colab disconnects are designed for, not hoped against.** Everything lands in
`Drive/MyDrive/atlas_corrosion` rather than `/content`; a checkpoint carrying
optimiser and scheduler state is written every epoch; saves are atomic, so a
session killed mid-write leaves the previous checkpoint intact; re-running the
training cell prints *resuming from epoch N* instead of starting over; and
`TIME_BUDGET_MIN` stops the loop cleanly before Colab's ceiling does. After a
disconnect the recovery procedure is: reconnect, Run all, wait.

The dataset in `dataset/corrovision-dataset-v1_semantic_export` is registered
automatically on boot as a topic dataset — in place, not copied — so an intern
can attach it to a run and `atlas.dataset()` streams that exact file.

`templates/corrosion_unet/corrosion_kit.py` is the single file all five
notebooks and the deployed app import: discovery, label space, dataset, U-Net,
losses, metrics, checkpointing and inference. Each notebook writes its own copy
next to itself, so nothing depends on reaching this server, and
`templates/corrosion_app/` is the Streamlit app that notebook 5 ships.
`templates/corrosion_unet/` remains the fuller reference — package, CLI trainer
and a Dockerfile.

| Command | What |
|---|---|
| `python tests/test_units.py` | 81 unit checks over metrics, model, losses, data discovery and `app.py` source. |
| `python tests/test_kit.py` | 52 checks on `corrosion_kit.py`: discovery, the background decision, NEAREST mask resizing, damped weights, IoU that refuses to be fooled by a background-only model, atomic checkpoints, and the shipped app's source. |
| `python tests/test_e2e.py` | 54 checks: generates data, really trains, reloads the checkpoint, predicts, then boots the Streamlit app and hits it over HTTP. `--fast` skips the quality bars. |
| `python tests/test_notebook.py` | 46 checks that execute all five playground notebooks in order against real data — including killing training and resuming it — and confirm the bundle the last one builds is deployable. |

- `docs/PRD.md` — full product requirements, design rationale and verification log
- `docs/SYSTEM_DESIGN.md` — architecture, data model, sequence flows

---

## Troubleshooting

### I pulled the latest code but the new pages are missing

The compiled interface (`backend/app/static/`) is deliberately **not** in git —
build output does not belong in version control. So `git pull` updates the
source but never the bundle your server actually serves, and anything newly
added returns 404.

`python run.py` fingerprints the frontend source and rebuilds automatically when
it no longer matches the bundle, so a plain start is enough. To force it:

```bash
python run.py --build
```

`python run.py --check` reports the bundle as **STALE** when this is the cause.
If Node.js is missing, the rebuild cannot run and `run.py` says so explicitly
rather than serving the old interface in silence.

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
