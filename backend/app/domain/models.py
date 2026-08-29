"""SQLModel tables. JSON-ish payloads stored as TEXT for SQLite portability."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Field, SQLModel
from sqlalchemy import UniqueConstraint

from app.domain.enums import (
    AppFramework,
    AssetKind,
    CheckStatus,
    ComputeTarget,
    ContentStatus,
    DeploymentStatus,
    LessonBlockType,
    Role,
    RunStatus,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JSONMixin:
    """Helpers so services never hand-roll json.loads on payload columns."""

    @staticmethod
    def loads(raw: str | None, default: Any = None) -> Any:
        if not raw:
            return default if default is not None else {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default if default is not None else {}

    @staticmethod
    def dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, default=str)


class User(SQLModel, table=True):
    __tablename__ = "users"
    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    full_name: str
    hashed_password: str = ""
    google_sub: str | None = Field(default=None, index=True)
    avatar_url: str = ""
    role: Role = Field(default=Role.INTERN)
    cohort: str = ""
    is_active: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class Assignment(SQLModel, table=True):
    """A supervisor granting one intern access to one topic.

    In production an intern sees only what they have been assigned; in
    development everything is open so the platform is explorable out of the
    box. Supervisors, admins and viewers are never restricted.
    """
    __tablename__ = "assignments"
    __table_args__ = (UniqueConstraint("user_id", "topic_id", name="uq_assignment"),)
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id")
    topic_id: int = Field(index=True, foreign_key="topics.id")
    assigned_by: int = Field(foreign_key="users.id")
    note: str = ""
    due_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Topic(SQLModel, table=True):
    """One internship topic (e.g. 'P&ID Extractor')."""
    __tablename__ = "topics"
    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True)
    order_index: int = 0
    title: str
    subtitle: str = ""
    summary: str = ""
    difficulty: str = "beginner"
    estimated_hours: int = 8
    accent: str = "#5B8C6E"
    icon: str = "sparkles"
    heavy_compute: bool = False
    task_type: str = "classification"   # classification | regression | forecasting | segmentation | extraction
    xp_reward: int = 100
    status: ContentStatus = Field(default=ContentStatus.PUBLISHED)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Lesson(SQLModel, table=True):
    """A game 'stage' inside a topic."""
    __tablename__ = "lessons"
    id: int | None = Field(default=None, primary_key=True)
    topic_id: int = Field(index=True, foreign_key="topics.id")
    slug: str = Field(index=True)
    order_index: int = 0
    title: str
    hook: str = ""                 # one-line plain-language hook
    duration_minutes: int = 10
    xp_reward: int = 25
    status: ContentStatus = Field(default=ContentStatus.PUBLISHED)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class LessonBlock(SQLModel, table=True):
    """Atomic content unit authored in the CMS block editor."""
    __tablename__ = "lesson_blocks"
    id: int | None = Field(default=None, primary_key=True)
    lesson_id: int = Field(index=True, foreign_key="lessons.id")
    order_index: int = 0
    block_type: LessonBlockType = Field(default=LessonBlockType.TEXT)
    payload_json: str = "{}"
    created_at: datetime = Field(default_factory=utcnow)


class Progress(SQLModel, table=True):
    __tablename__ = "progress"
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id")
    lesson_id: int = Field(index=True, foreign_key="lessons.id")
    topic_id: int = Field(index=True)
    completed: bool = False
    score: float = 0.0
    xp_earned: int = 0
    completed_at: datetime | None = None


class Asset(SQLModel, table=True):
    """Uploaded file: dataset, PPT deck, artifact or image."""
    __tablename__ = "assets"
    id: int | None = Field(default=None, primary_key=True)
    topic_id: int | None = Field(default=None, index=True)
    lesson_id: int | None = Field(default=None, index=True)
    kind: AssetKind = Field(default=AssetKind.DATASET)
    title: str = ""
    description: str = ""
    filename: str = ""
    stored_path: str = ""
    content_type: str = ""
    size_bytes: int = 0
    checksum: str = ""
    version: int = 1
    row_count: int | None = None
    column_count: int | None = None
    slide_count: int | None = None
    preview_json: str = "{}"
    stage: str = "raw"             # raw | cleaned | features | split
    uploaded_by: int | None = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow)


class Notebook(SQLModel, table=True):
    """Playground notebook bound to a topic."""
    __tablename__ = "notebooks"
    id: int | None = Field(default=None, primary_key=True)
    topic_id: int = Field(index=True, foreign_key="topics.id")
    slug: str = Field(index=True)
    title: str
    description: str = ""
    default_target: ComputeTarget = Field(default=ComputeTarget.LOCAL_CPU)
    requires_gpu: bool = False
    content_json: str = "{}"       # nbformat v4 document
    requirements: str = ""
    version: int = 1
    updated_by: int | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Run(SQLModel, table=True):
    """One execution of a notebook on some compute target."""
    __tablename__ = "runs"
    id: int | None = Field(default=None, primary_key=True)
    notebook_id: int = Field(index=True, foreign_key="notebooks.id")
    topic_id: int = Field(index=True)
    user_id: int = Field(index=True)
    target: ComputeTarget = Field(default=ComputeTarget.LOCAL_CPU)
    status: RunStatus = Field(default=RunStatus.PENDING)
    dataset_asset_id: int | None = None
    params_json: str = "{}"
    metrics_json: str = "{}"
    logs: str = ""
    callback_token: str = Field(default="", index=True)
    external_url: str = ""
    error: str = ""
    duration_seconds: float = 0.0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Deployment(SQLModel, table=True):
    """A Streamlit/Gradio app submitted by an intern."""
    __tablename__ = "deployments"
    id: int | None = Field(default=None, primary_key=True)
    topic_id: int = Field(index=True)
    user_id: int = Field(index=True)
    name: str
    slug: str = Field(index=True, unique=True)
    framework: AppFramework = Field(default=AppFramework.STREAMLIT)
    entrypoint: str = "app.py"
    source_kind: str = "upload"    # upload | git
    source_ref: str = ""
    bundle_path: str = ""
    status: DeploymentStatus = Field(default=DeploymentStatus.DRAFT)
    url: str = ""
    internal_port: int | None = None
    process_pid: int | None = None
    whimsical_url: str = ""
    build_logs: str = ""
    readiness_score: int = 0
    published_to_portal: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ComplianceCheck(SQLModel, table=True):
    """Result of one graduation-rubric rule against a deployment."""
    __tablename__ = "compliance_checks"
    id: int | None = Field(default=None, primary_key=True)
    deployment_id: int = Field(index=True, foreign_key="deployments.id")
    rule_id: str = Field(index=True)
    label: str = ""
    status: CheckStatus = Field(default=CheckStatus.PENDING)
    detail: str = ""
    evidence: str = ""
    auto: bool = True
    checked_at: datetime = Field(default_factory=utcnow)


class ActivityLog(SQLModel, table=True):
    __tablename__ = "activity_logs"
    id: int | None = Field(default=None, primary_key=True)
    user_id: int | None = Field(default=None, index=True)
    actor_name: str = ""
    action: str = ""
    entity_type: str = ""
    entity_id: int | None = None
    topic_id: int | None = Field(default=None, index=True)
    detail: str = ""
    created_at: datetime = Field(default_factory=utcnow, index=True)
