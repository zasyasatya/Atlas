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
    coolify_base_url: str = ""
    coolify_token: str = ""
    coolify_project_uuid: str = ""
    coolify_server_uuid: str = ""

    # google oauth
    google_client_id: str = ""
    google_client_secret: str = ""

    seed_demo_data: bool = True

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.storage_dir / 'atlas.db'}"

    def ensure_dirs(self) -> None:
        for sub in ("datasets", "decks", "notebooks", "deployments", "artifacts", "runs"):
            (self.storage_dir / sub).mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


settings = get_settings()
