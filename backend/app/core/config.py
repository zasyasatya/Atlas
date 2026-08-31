"""Application configuration. Single source of truth for env-driven settings."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATLAS_", env_file=".env", extra="ignore")

    app_name: str = "ATLAS"
    app_tagline: str = "AI Internship Operating System"
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
