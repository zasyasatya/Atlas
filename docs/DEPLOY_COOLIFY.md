# Deploying ATLAS to Coolify

Step-by-step guide. Takes about 10 minutes.

---

## 1. Prerequisites

- A Coolify instance (v4+) with a server attached
- A Git repository containing this project
- A domain or subdomain pointed at your Coolify server, e.g. `atlas.yourdomain.com`

---

## 2. Create the application

1. Coolify → **Projects** → your project → **+ New Resource**
2. Choose **Application** → **Public Repository** (or Private, with a deploy key)
3. Repository URL: your ATLAS repo. Branch: `main`
4. **Build Pack: Dockerfile**
5. Dockerfile location: `/Dockerfile` (repository root)
6. **Port: 8000**

Coolify detects the multi-stage build automatically. The first build takes 3–5 minutes because it
installs Node dependencies and builds the Next.js export; later builds are cached.

---

## 3. Persistent storage

**This is essential.** Without it every redeploy wipes the database, uploads and deployed apps.

Coolify → your application → **Storages** → **+ Add**

| Field | Value |
|---|---|
| Name | `atlas-storage` |
| Mount path | `/app/storage` |

---

## 4. Environment variables

Coolify → your application → **Environment Variables**.

### Required

| Variable | Value |
|---|---|
| `ATLAS_SECRET_KEY` | Long random string. Generate with `openssl rand -hex 32` |
| `ATLAS_PUBLIC_BASE_URL` | `https://atlas.yourdomain.com` |

`ATLAS_PUBLIC_BASE_URL` must be the real public URL. Notebooks running on Colab and Kaggle call back
to this address to report metrics and upload artifacts — if it is wrong or empty, remote runs will
execute but nothing will come back.

### Recommended

| Variable | Value | Effect |
|---|---|---|
| `ATLAS_SEED_DEMO_DATA` | `true` for the first deploy, then `false` | Seeds 6 topics, 18 lessons, 6 notebooks and demo accounts |
| `ATLAS_ENVIRONMENT` | `production` | Already set in the image |

### Colab GPU bridge (optional, recommended)

| Variable | Value |
|---|---|
| `ATLAS_GITHUB_TOKEN` | GitHub PAT with `repo` scope |
| `ATLAS_COLAB_GITHUB_REPO` | `your-org/atlas-notebooks` |
| `ATLAS_COLAB_GITHUB_BRANCH` | `main` |

With these set, dispatching a GPU run pushes the notebook to the repo and produces a true one-click
`Open in Colab` link. Without them ATLAS falls back to URL import, which still works — it just asks
the learner for one extra confirmation.

### Kaggle GPU bridge (optional)

| Variable | Value |
|---|---|
| `ATLAS_KAGGLE_USERNAME` | From `kaggle.json` |
| `ATLAS_KAGGLE_KEY` | From `kaggle.json` |

Get these at Kaggle → Account → **Create New API Token**. This unlocks fully headless GPU training:
ATLAS submits the kernel, Kaggle runs it on a T4/P100, and results stream back with no browser tab
open. Free tier gives 30 GPU-hours per week.

### Deploying intern apps into Coolify itself (optional)

By default `ATLAS_DEPLOY_DRIVER=local_process` runs intern apps as child processes inside the ATLAS
container. That is fine for a trusted cohort and demos. For proper isolation:

| Variable | Value |
|---|---|
| `ATLAS_DEPLOY_DRIVER` | `coolify` |
| `ATLAS_COOLIFY_BASE_URL` | `https://coolify.yourdomain.com` |
| `ATLAS_COOLIFY_TOKEN` | Coolify → Keys & Tokens → API tokens |
| `ATLAS_COOLIFY_PROJECT_UUID` | From the target project URL |
| `ATLAS_COOLIFY_SERVER_UUID` | From the target server URL |

Each intern app then becomes its own Coolify application with its own container.

### Google SSO (optional)

| Variable | Value |
|---|---|
| `ATLAS_GOOGLE_CLIENT_ID` | OAuth 2.0 client ID |
| `ATLAS_GOOGLE_CLIENT_SECRET` | OAuth 2.0 client secret |

Authorised redirect URI: `https://atlas.yourdomain.com/login`.

### Postgres instead of SQLite (optional)

Add a Postgres resource in Coolify, then set:

```
ATLAS_DATABASE_URL=postgresql+psycopg://user:password@host:5432/atlas
```

and add `psycopg[binary]` to `backend/requirements.txt`. SQLite is perfectly adequate for a single
cohort; switch when you need concurrent writes from multiple supervisors.

---

## 5. Domain and TLS

Coolify → your application → **Domains** → add `https://atlas.yourdomain.com`.
Coolify provisions Let's Encrypt automatically. Make sure the value matches
`ATLAS_PUBLIC_BASE_URL` exactly, including the scheme.

---

## 6. Deploy

Press **Deploy**. Watch the build log; the health check at `/api/health` gates the rollout, so a
broken build never replaces a working container.

Verify:

```bash
curl https://atlas.yourdomain.com/api/health
# {"status":"ok","app":"ATLAS","environment":"production","deploy_driver":"local_process"}
```

Then open the domain and sign in with `supervisor@atlas.id` / `supervisor123`.

**Change the demo passwords immediately**, or set `ATLAS_SEED_DEMO_DATA=false` and create real
accounts before opening access.

---

## 7. Post-deploy checklist

- [ ] `/api/health` returns ok
- [ ] Login works and the dashboard shows 6 topics
- [ ] Settings page shows the expected "configured" badges for Colab/Kaggle
- [ ] Upload a small CSV in Datasets — schema preview appears
- [ ] Launch a CPU run in Playground — metrics come back
- [ ] Launch a GPU run on the P&ID topic — the Colab link opens correctly
- [ ] Demo accounts removed or passwords rotated
- [ ] Storage volume is mounted (redeploy and confirm data survives)

---

## Troubleshooting

**Build fails at `npm ci`** — no `package-lock.json` in the repo. The Dockerfile falls back to
`npm install`, but committing the lockfile makes builds reproducible and faster.

**Blank page, API works** — the frontend export did not copy. Confirm the build log shows
`Generating static pages` and that stage 3 copies `/build/out`.

**Remote runs never report back** — `ATLAS_PUBLIC_BASE_URL` is wrong, or the domain is not publicly
reachable. Colab cannot call `localhost`. Check the value on the Settings page.

**Data disappears after redeploy** — the `/app/storage` volume is missing. Add it in Storages.

**Intern apps fail to start** — with `local_process`, the internal ports 8600–8620 must be free
inside the container. Those ports are never exposed publicly: each app is served under a virtual
directory on the main domain (`https://<domain>/app/<slug>`) and nginx routes `/app/<slug>` to the
internal port. After apps are running, open the Portal → **Proxy config** (or
`GET /api/deployments/proxy-config`) and drop the generated `location` blocks into your nginx
`server{}` block so the whole cohort is reachable on ports 80/443. The path prefix defaults to
`app` (`ATLAS_DEPLOY_URL_PREFIX`).
