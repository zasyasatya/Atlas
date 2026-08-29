"""Reference pipelines - complete, working implementations interns can read.

The Stage 6 lesson tells an intern to look at `templates/corrosion_unet/app.py`.
That instruction was impossible to follow: the folder only existed in the git
repo, and the whole point of ATLAS is that an intern never needs codebase
access. This module serves those folders through the API so the material it
references is actually reachable.

Files are read on demand from disk rather than copied into the database, so a
supervisor who edits a template sees the change immediately.
"""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

TEMPLATE_ROOT = Path(__file__).resolve().parents[3] / "templates"

# Anything matching these is build output, a local virtualenv, or a trained
# checkpoint. None of it belongs in a browsable listing or a download.
EXCLUDED_DIRS = {
    ".venv-app", ".venv", "venv", "runs", "data", "__pycache__", ".pytest_cache",
    ".git", "node_modules", ".ipynb_checkpoints", ".nbtest", ".probe",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".pt", ".pth", ".ckpt", ".db", ".sqlite"}
MAX_PREVIEW_BYTES = 400_000

LANGUAGE_BY_SUFFIX = {
    ".py": "python", ".md": "markdown", ".txt": "text", ".json": "json",
    ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".sh": "bash",
    ".cfg": "ini", ".ini": "ini", ".csv": "csv",
}


@dataclass
class PipelineFile:
    path: str
    size: int
    language: str


@dataclass
class Pipeline:
    slug: str
    title: str
    summary: str
    topic_slug: str
    folder: str
    entrypoint: str
    highlights: list[str] = field(default_factory=list)


# Registered reference pipelines. Adding one here is enough to publish it.
PIPELINES: list[Pipeline] = [
    Pipeline(
        slug="corrosion-unet",
        title="Corrosion U-Net - full pipeline",
        summary=(
            "The complete reference implementation for Topic 6: dataset discovery, "
            "a U-Net built from scratch, damped class weighting, combined "
            "cross-entropy and Dice loss, IoU metrics, a CLI trainer, a Streamlit "
            "app that meets all five rubric rules, and a Dockerfile."
        ),
        topic_slug="corrosion-segmentation",
        folder="corrosion_unet",
        entrypoint="app.py",
        highlights=[
            "corrosion/model.py - U-Net with skip connections, written out in full",
            "corrosion/dataset.py - why median-frequency weighting is damped to 8:1",
            "corrosion/metrics.py - per-class IoU, and why not pixel accuracy",
            "corrosion/train.py - seed_everything, AMP, checkpointing, reports",
            "app.py - single + bulk input, four documentation sections, confidence",
            "tests/ - 81 unit checks, a 54-check end-to-end run, 16 notebook checks",
        ],
    ),
    Pipeline(
        slug="streamlit-starter",
        title="Streamlit starter",
        summary=("A minimal Streamlit app that already scores 100% on the graduation "
                 "rubric. Start here for any tabular or NLP topic."),
        topic_slug="",
        folder="streamlit_starter",
        entrypoint="app.py",
        highlights=["Scores 5/5 on the rubric as shipped"],
    ),
    Pipeline(
        slug="gradio-starter",
        title="Gradio starter",
        summary=("The same rubric-complete starter, built with Gradio instead of "
                 "Streamlit."),
        topic_slug="",
        folder="gradio_starter",
        entrypoint="app.py",
        highlights=["Scores 5/5 on the rubric as shipped"],
    ),
]

BY_SLUG = {p.slug: p for p in PIPELINES}


def _is_excluded(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if any(part in EXCLUDED_DIRS for part in rel.parts):
        return True
    return path.suffix.lower() in EXCLUDED_SUFFIXES


def _root_for(pipeline: Pipeline) -> Path:
    return TEMPLATE_ROOT / pipeline.folder


def exists(pipeline: Pipeline) -> bool:
    return _root_for(pipeline).is_dir()


def list_files(pipeline: Pipeline) -> list[PipelineFile]:
    """Every readable source file, shallowest first then alphabetical."""
    root = _root_for(pipeline)
    if not root.is_dir():
        return []
    files: list[PipelineFile] = []
    for path in root.rglob("*"):
        if not path.is_file() or _is_excluded(path, root):
            continue
        rel = path.relative_to(root).as_posix()
        files.append(PipelineFile(
            path=rel,
            size=path.stat().st_size,
            language=LANGUAGE_BY_SUFFIX.get(path.suffix.lower(), "text"),
        ))
    files.sort(key=lambda f: (f.path.count("/"), f.path))
    return files


def read_file(pipeline: Pipeline, rel_path: str) -> tuple[str, str]:
    """Return (text, language) for one file.

    Raises FileNotFoundError if the path escapes the pipeline folder, is
    excluded, or does not exist - path traversal is rejected by resolving the
    candidate and confirming it is still inside the root.
    """
    root = _root_for(pipeline).resolve()
    candidate = (root / rel_path).resolve()

    if not candidate.is_relative_to(root):
        raise FileNotFoundError("path escapes the pipeline")
    if not candidate.is_file() or _is_excluded(candidate, root):
        raise FileNotFoundError(rel_path)
    if candidate.stat().st_size > MAX_PREVIEW_BYTES:
        raise FileNotFoundError("file is too large to preview")

    text = candidate.read_text(encoding="utf-8", errors="replace")
    return text, LANGUAGE_BY_SUFFIX.get(candidate.suffix.lower(), "text")


def build_zip(pipeline: Pipeline) -> bytes:
    """A downloadable archive, excluding venvs, checkpoints and sample data."""
    root = _root_for(pipeline)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(root.rglob("*")):
            if path.is_file() and not _is_excluded(path, root):
                zf.write(path, Path(pipeline.folder) / path.relative_to(root))
    buf.seek(0)
    return buf.read()


def summarise(pipeline: Pipeline) -> dict:
    files = list_files(pipeline)
    return {
        "slug": pipeline.slug,
        "title": pipeline.title,
        "summary": pipeline.summary,
        "topic_slug": pipeline.topic_slug,
        "entrypoint": pipeline.entrypoint,
        "highlights": pipeline.highlights,
        "available": exists(pipeline),
        "file_count": len(files),
        "total_bytes": sum(f.size for f in files),
    }
