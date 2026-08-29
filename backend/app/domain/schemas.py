"""Pydantic I/O contracts for the API layer."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from app.domain.enums import (
    AppFramework,
    ComputeTarget,
    ContentStatus,
    LessonBlockType,
    Role,
)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: Role
    cohort: str = ""
    avatar_url: str = ""


class BlockIn(BaseModel):
    block_type: LessonBlockType
    payload: dict[str, Any] = Field(default_factory=dict)
    order_index: int = 0


class BlockOut(BlockIn):
    id: int


class LessonIn(BaseModel):
    title: str
    slug: str = ""
    hook: str = ""
    duration_minutes: int = 10
    xp_reward: int = 25
    order_index: int = 0
    status: ContentStatus = ContentStatus.PUBLISHED
    blocks: list[BlockIn] = Field(default_factory=list)


class LessonOut(BaseModel):
    id: int
    topic_id: int
    slug: str
    title: str
    hook: str
    duration_minutes: int
    xp_reward: int
    order_index: int
    status: ContentStatus
    blocks: list[BlockOut] = Field(default_factory=list)
    completed: bool = False


class TopicIn(BaseModel):
    title: str
    slug: str = ""
    subtitle: str = ""
    summary: str = ""
    difficulty: str = "beginner"
    estimated_hours: int = 8
    accent: str = "#5B8C6E"
    icon: str = "sparkles"
    heavy_compute: bool = False
    task_type: str = "classification"
    xp_reward: int = 100
    order_index: int = 0
    status: ContentStatus = ContentStatus.PUBLISHED


class TopicOut(TopicIn):
    id: int
    lesson_count: int = 0
    completed_lessons: int = 0
    notebook_count: int = 0
    dataset_count: int = 0
    deck_count: int = 0


class TopicDetail(TopicOut):
    lessons: list[LessonOut] = Field(default_factory=list)


class NotebookIn(BaseModel):
    title: str
    slug: str = ""
    description: str = ""
    default_target: ComputeTarget = ComputeTarget.LOCAL_CPU
    requires_gpu: bool = False
    requirements: str = ""
    content: dict[str, Any] = Field(default_factory=dict)


class NotebookOut(BaseModel):
    id: int
    topic_id: int
    slug: str
    title: str
    description: str
    default_target: ComputeTarget
    requires_gpu: bool
    requirements: str
    version: int
    updated_at: datetime
    cell_count: int = 0


class RunRequest(BaseModel):
    notebook_id: int
    target: ComputeTarget = ComputeTarget.LOCAL_CPU
    dataset_asset_id: int | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class RunOut(BaseModel):
    id: int
    notebook_id: int
    topic_id: int
    target: ComputeTarget
    status: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    logs: str = ""
    external_url: str = ""
    error: str = ""
    duration_seconds: float = 0.0
    created_at: datetime
    user_name: str = ""
    notebook_title: str = ""


class RunCallback(BaseModel):
    """Posted by Colab/Kaggle notebooks through the atlas_bridge helper."""
    status: str = "running"
    metrics: dict[str, Any] = Field(default_factory=dict)
    logs: str = ""
    error: str = ""
    external_url: str = ""


class DeploymentIn(BaseModel):
    name: str
    topic_id: int
    framework: AppFramework = AppFramework.STREAMLIT
    entrypoint: str = "app.py"
    whimsical_url: str = ""


class DeploymentOut(BaseModel):
    id: int
    name: str
    slug: str
    topic_id: int
    topic_title: str = ""
    user_id: int
    owner_name: str = ""
    framework: AppFramework
    entrypoint: str
    status: str
    url: str
    whimsical_url: str
    readiness_score: int
    published_to_portal: bool
    build_logs: str = ""
    created_at: datetime
    checks: list["CheckOut"] = Field(default_factory=list)


class CheckOut(BaseModel):
    rule_id: str
    label: str
    status: str
    detail: str = ""
    auto: bool = True


class AssetOut(BaseModel):
    id: int
    topic_id: int | None
    kind: str
    title: str
    description: str
    filename: str
    size_bytes: int
    version: int
    stage: str
    row_count: int | None = None
    column_count: int | None = None
    slide_count: int | None = None
    preview: dict[str, Any] = Field(default_factory=dict)
    uploader_name: str = ""
    created_at: datetime


class ActivityOut(BaseModel):
    id: int
    actor_name: str
    action: str
    entity_type: str
    detail: str
    topic_id: int | None
    created_at: datetime


TokenResponse.model_rebuild()
DeploymentOut.model_rebuild()
