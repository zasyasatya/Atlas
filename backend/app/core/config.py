"""Application configuration. Single source of truth for env-driven settings."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATLAS_", env_file=".env", extra="ignore")

    # ---- public identity ----------------------------------------------------
    # Everything the user sees about *what this product is called* reads these
    # four values: the browser tab title, the sign-in screen, the sidebar, the
    # CLI banner and the manual footer. Rebranding (or white-labelling for a
    # client) is therefore an env change, never a code change. The frontend
    # fetches them from GET /api/config and only falls back to its own defaults
    # until the first response arrives.
    app_name: str = "ATLAS"
    app_tagline: str = "Applied AI & Data Research Platform"
    # Short label under the wordmark (sidebar rail, sign-in card).
    app_tagline_short: str = "Applied AI Platform"
    # One-sentence promise, shown on the sign-in screen and page headers.
    app_subtitle: str = ("Datasets, models and live apps in one place - from the "
                         "first notebook to a deployed app on your own domain.")
    # Optional link to external docs; empty = the built-in manual is the docs.
    docs_url: str = ""

    environment: str = "development"
    secret_key: str = "change-me-in-production-please-32chars"
    access_token_ttl_minutes: int = 60 * 24 * 7

    # storage
    storage_dir: Path = BASE_DIR / "storage"
    database_url: str = ""

    # frontend static bundle (Next.js export)
    static_dir: Path = BASE_DIR / "backend" / "app" / "static"

    # compute bridges
    colab_github_repo: str = ""          # e.g. "org/atlas-notebooks"
    colab_github_branch: str = "main"
    github_token: str = ""
    kaggle_username: str = ""
    kaggle_key: str = ""
    public_base_url: str = ""            # used by notebooks to call back home

    # deployment engine
    deploy_driver: str = "local_process"  # local_process | coolify | manifest
    deploy_port_start: int = 8600
    deploy_port_end: int = 8620
    # Deployed apps are served under this path on the main domain (a virtual
    # directory) instead of exposing a separate port per app. e.g. prefix "app"
    # + slug "my-app" -> https://<domain>/app/my-app
    deploy_url_prefix: str = "app"
    # ATLAS proxies those paths to the app's internal port itself, so a virtual
    # directory works with no nginx, no reload and nothing to install. Turn this
    # off only if an external proxy owns the whole domain (see nginx_* below):
    # with it off, app URLs fall back to the app's own port.
    deploy_builtin_proxy: bool = True
    # How long a slug -> port lookup is cached, in seconds. Kept short so a
    # freshly deployed (or just stopped) app is reachable almost immediately
    # while a burst of asset requests still hits the cache.
    deploy_route_ttl_seconds: float = 2.0
    coolify_base_url: str = ""
    coolify_token: str = ""
    coolify_project_uuid: str = ""
    coolify_server_uuid: str = ""

    # reverse proxy (nginx) automation.
    # Every deployed app automatically gets its own nginx snippet that serves it
    # as a virtual directory, so nginx needs no manual edits and other apps are
    # never touched. By default snippets + a ready-to-use vhost are written under
    # the persistent storage dir; point these at a live nginx path to make the
    # reload fully automatic (operator opt-in, never touches system nginx out of
    # the box).
    # Directory that holds one managed <location> file per app:
    nginx_conf_dir: str = ""
    # Optional path for a full standalone vhost (leave empty to keep it in storage):
    nginx_vhost_file: str = ""
    # Command that reloads nginx after the snippets change. Empty = auto-detect
    # (`nginx -s reload`). Override for dockerised/privileged setups, e.g.
    # "sudo nginx -s reload" or "docker exec atlas-proxy nginx -s reload".
    nginx_reload_cmd: str = ""
    # Reload nginx automatically after a successful `nginx -t`. Set false to only
    # write the files and let an operator reload.
    nginx_auto_reload: bool = True
    # Opt-in: also keep a ready-to-use vhost installed *inside* nginx, so an
    # operator who does want nginx in front (TLS, rate limiting, static assets)
    # never copies a file by hand. ATLAS installs it into sites-available +
    # sites-enabled (Debian layout) or conf.d (RHEL/Alpine layout), writes only
    # its own `atlas.conf`, refuses to overwrite a file it does not own, and
    # rolls back if `nginx -t` rejects the result. Off by default because
    # nothing needs it: apps are already reachable through the built-in proxy.
    nginx_auto_install: bool = False
    nginx_sites_available: str = "/etc/nginx/sites-available"
    nginx_sites_enabled: str = "/etc/nginx/sites-enabled"
    nginx_conf_d: str = "/etc/nginx/conf.d"
    # Where the portal/UI itself is reached, for the fallback vhost that routes
    # everything that is NOT an /app/<slug> virtual directory.
    nginx_upstream: str = "http://127.0.0.1:8000"

    # google oauth
    google_client_id: str = ""
    google_client_secret: str = ""
    # Optional comma-separated hosted-domain allowlist, e.g.
    # "pertamina.com,contractor.co.id". Empty means any verified Google
    # account may sign in (and lands as an Intern).
    google_allowed_domains: str = ""

    seed_demo_data: bool = True

    @property
    def is_production(self) -> bool:
        """
        True unless this is an explicitly non-production environment.

        Deliberately fail-closed: anything other than a known development-style
        value is treated as production, so a typo in ATLAS_ENVIRONMENT hides
        operator material rather than exposing it.
        """
        return self.environment.strip().lower() not in {
            "development", "dev", "local", "test", "testing",
        }

    @property
    def brand(self) -> dict:
        """The public identity, exactly as served by ``GET /api/config``.

        The frontend renders these fields and nothing else about naming, so a new
        brand surface (an email footer, a PDF stamp) consumes this dict rather
        than inventing its own constant.
        """
        return {
            "name": self.app_name,
            "tagline": self.app_tagline,
            "label": self.app_tagline_short,
            "subtitle": self.app_subtitle,
            "docs_url": self.docs_url,
        }

    @property
    def deploy_prefix(self) -> str:
        """Normalised virtual-directory prefix, never a reserved ATLAS path.

        A prefix like ``api`` would shadow the API (and ``_next`` the UI bundle),
        silently breaking the platform, so anything reserved falls back to
        ``app``.
        """
        raw = (self.deploy_url_prefix or "").strip("/")
        head = raw.split("/", 1)[0]
        reserved = {"api", "_next", "static", "storage", "favicon.ico", "docs", "manual"}
        if not head or head in reserved:
            return "app"
        return raw

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.storage_dir / 'atlas.db'}"

    def ensure_dirs(self) -> None:
        for sub in ("datasets", "decks", "notebooks", "deployments", "artifacts",
                    "runs", "appdata", "nginx"):
            (self.storage_dir / sub).mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


settings = get_settings()
