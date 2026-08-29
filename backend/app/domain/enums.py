"""Domain enumerations shared across services and API."""
from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    SUPERVISOR = "supervisor"
    INTERN = "intern"
    VIEWER = "viewer"


class LessonBlockType(StrEnum):
    """Block kinds a supervisor can add from the CMS - no code access required."""
    TEXT = "text"
    CALLOUT = "callout"
    IMAGE = "image"
    ARCHITECTURE = "architecture"   # rendered node/edge diagram
    QUIZ = "quiz"
    CODE = "code"
    VIDEO = "video"
    FLASHCARD = "flashcard"


class ContentStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class AssetKind(StrEnum):
    DATASET = "dataset"
    DECK = "deck"
    ARTIFACT = "artifact"
    IMAGE = "image"


class RunStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ComputeTarget(StrEnum):
    LOCAL_CPU = "local_cpu"
    COLAB_GPU = "colab_gpu"
    KAGGLE_GPU = "kaggle_gpu"


class DeploymentStatus(StrEnum):
    DRAFT = "draft"
    BUILDING = "building"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"


class AppFramework(StrEnum):
    STREAMLIT = "streamlit"
    GRADIO = "gradio"


class CheckStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    PENDING = "pending"
