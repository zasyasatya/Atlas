"""Seeds the six internship topics, game-themed lessons and playground notebooks.

Everything here is also reachable from the CMS UI - the seed only guarantees a
supervisor never faces an empty platform on day one.
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlmodel import Session, select

from app.core.security import hash_password
from app.services.corrosion_lessons import corrosion_lessons
from app.domain.enums import (AppFramework, ComputeTarget, DeploymentStatus,
                              LessonBlockType, Role)
from app.domain.models import (Deployment, Lesson, LessonBlock, Notebook, Topic,
                               User)
from app.services import notebook_factory as nf

USERS = [
    ("supervisor@atlas.id", "Dewi Supervisor", Role.SUPERVISOR, "supervisor123", "Staff"),
    ("admin@atlas.id", "Rangga Admin", Role.ADMIN, "admin123", "Staff"),
    ("intern@atlas.id", "Putu Intern", Role.INTERN, "intern123", "Batch 2026-A"),
    ("viewer@atlas.id", "Sari Viewer", Role.VIEWER, "viewer123", "Guest"),
]


def _blocks(*items: tuple[LessonBlockType, dict]) -> list[LessonBlock]:
    return [LessonBlock(order_index=i, block_type=t, payload_json=json.dumps(p, ensure_ascii=False))
            for i, (t, p) in enumerate(items)]


def _lesson(slug, title, hook, minutes, xp, order, blocks):
    return {"slug": slug, "title": title, "hook": hook, "duration_minutes": minutes,
            "xp_reward": xp, "order_index": order, "blocks": blocks}


def _intro_lessons(topic_word: str, analogy: str, steps: list[str]) -> list[dict]:
    """Standard 3-stage arc every topic gets: Briefing -> Blueprint -> Boss fight."""
    return [
        _lesson("briefing", "Stage 1 - Mission Briefing",
                f"What problem are we actually solving with {topic_word}?", 8, 20, 0,
                _blocks(
                    (LessonBlockType.CALLOUT, {"tone": "quest", "title": "Your mission",
                                               "body": f"{analogy}"}),
                    (LessonBlockType.TEXT, {"body": "Before touching a model, write one sentence: "
                                                     "*who* is doing this work today, *how long* it takes, "
                                                     "and *what number* would prove you helped. "
                                                     "If you cannot fill that sentence, you are not ready to train."}),
                    (LessonBlockType.FLASHCARD, {"cards": [
                        {"front": "Baseline", "back": "The dumbest solution that already works. Always measure against it."},
                        {"front": "Ground truth", "back": "The labelled answer you trust. Only as good as the person who labelled it."},
                    ]}),
                )),
        _lesson("blueprint", "Stage 2 - Read the Blueprint",
                "How the pieces connect, end to end.", 12, 30, 1,
                _blocks(
                    (LessonBlockType.ARCHITECTURE, {
                        "title": f"{topic_word} pipeline",
                        "nodes": [{"id": f"n{i}", "label": s, "note": ""} for i, s in enumerate(steps)],
                        "edges": [{"from": f"n{i}", "to": f"n{i+1}"} for i in range(len(steps) - 1)],
                    }),
                    (LessonBlockType.TEXT, {"body": "Each box is a place where things break. "
                                                     "When your metric looks wrong, walk the boxes left to right "
                                                     "and check the data leaving each one."}),
                )),
        _lesson("boss", "Stage 3 - Boss Fight",
                "Prove it with a number, not a vibe.", 15, 50, 2,
                _blocks(
                    (LessonBlockType.QUIZ, {"question": "Your model scores 99% accuracy on day one. What is the FIRST thing to suspect?",
                                            "options": ["The model is genuinely excellent",
                                                        "Data leakage or a trivially imbalanced target",
                                                        "The GPU was too fast",
                                                        "You need more epochs"],
                                            "answer": 1,
                                            "explanation": "99% on the first try almost always means the target leaked into the features, "
                                                           "or 99% of rows are one class. Check class balance and column provenance before celebrating."}),
                    (LessonBlockType.CALLOUT, {"tone": "warning", "title": "Graduation gate",
                                               "body": "Your web app must show a confidence score (classification) or MAPE (forecasting). "
                                                       "The Deployment tab checks this automatically."}),
                )),
    ]


TOPICS = [
    {
        "slug": "predictive-maintenance", "title": "Predictive Maintenance",
        "subtitle": "Tabular ML on sensor histories",
        "summary": "Predict equipment failure before it happens using vibration, temperature and runtime data.",
        "difficulty": "beginner", "hours": 10, "accent": "#5B8C6E", "icon": "activity",
        "heavy": False, "task": "classification", "xp": 100,
        "analogy": "A pump does not fail silently - it complains for weeks through vibration and heat. "
                   "You are building the thing that listens to those complaints and files a work order before the shutdown.",
        "steps": ["Sensor history", "Clean + resample", "Feature engineering", "Train classifier", "Confidence output", "Work order"],
        "nb": ("pm-playground", "Predictive Maintenance Playground", ComputeTarget.LOCAL_CPU, False,
               lambda: nf.tabular_notebook("Predictive Maintenance", "Topic 1 - Tabular ML")),
    },
    {
        "slug": "pid-extractor", "title": "P&ID Extractor",
        "subtitle": "Computer vision on engineering drawings",
        "summary": "Detect valves, pumps and instruments on P&ID sheets and rebuild the connectivity graph.",
        "difficulty": "advanced", "hours": 24, "accent": "#3F6B52", "icon": "scan",
        "heavy": True, "task": "extraction", "xp": 250,
        "analogy": "A P&ID is a map of a plant drawn by hand decades ago. Engineers still trace pipes with a finger and a ruler. "
                   "You are teaching a camera to read that map in seconds.",
        "steps": ["Scan / PDF", "Tile large drawing", "Detect symbols (YOLO)", "Trace pipe lines", "Build graph", "Export equipment list"],
        "nb": ("pid-playground", "P&ID Extractor Playground", ComputeTarget.COLAB_GPU, True,
               nf.pid_extractor_notebook),
    },
    {
        "slug": "report-nlp", "title": "Inspection Report NLP",
        "subtitle": "Turning free text into structured findings",
        "summary": "Classify inspection findings and pull equipment tags out of unstructured field reports.",
        "difficulty": "intermediate", "hours": 14, "accent": "#4F7D8C", "icon": "file-text",
        "heavy": False, "task": "classification", "xp": 150,
        "analogy": "Twenty years of inspection reports sit in Word files nobody can query. "
                   "You are turning that pile of prose into a table someone can actually filter.",
        "steps": ["Raw reports", "Clean + normalise", "TF-IDF / embeddings", "Classify finding", "Extract tags", "Structured table"],
        "nb": ("nlp-playground", "Report NLP Playground", ComputeTarget.LOCAL_CPU, False,
               lambda: nf.nlp_notebook("Inspection Report NLP", "Topic 3 - NLP")),
    },
    {
        "slug": "production-forecasting", "title": "Production Forecasting",
        "subtitle": "Time series with a mandatory MAPE",
        "summary": "Forecast daily production and report error the way the business reads it - as a percentage.",
        "difficulty": "intermediate", "hours": 14, "accent": "#8C7A4F", "icon": "trending-up",
        "heavy": False, "task": "forecasting", "xp": 150,
        "analogy": "Planners commit to numbers a month ahead. Being wrong by 3% is a rounding error; "
                   "being wrong by 30% is a cancelled cargo. Your job is to know which one you are.",
        "steps": ["Historical series", "Handle gaps", "Lag + calendar features", "Train regressor", "Backtest", "MAPE report"],
        "nb": ("forecast-playground", "Forecasting Playground", ComputeTarget.LOCAL_CPU, False,
               lambda: nf.forecasting_notebook("Production Forecasting", "Topic 4 - Time Series")),
    },
    {
        "slug": "sop-rag-assistant", "title": "SOP RAG Assistant",
        "subtitle": "Grounded answers from your own documents",
        "summary": "Build a retrieval-augmented assistant that answers procedure questions with citations.",
        "difficulty": "intermediate", "hours": 16, "accent": "#6B5B8C", "icon": "message-square",
        "heavy": False, "task": "extraction", "xp": 180,
        "analogy": "A new technician asks 'how do I purge this line?' and waits two days for an email. "
                   "You are building the thing that answers in four seconds - and shows which page it read.",
        "steps": ["SOP documents", "Chunk", "Embed + index", "Retrieve top-k", "Ground the answer", "Cite the source"],
        "nb": ("rag-playground", "RAG Assistant Playground", ComputeTarget.LOCAL_CPU, False,
               lambda: nf.rag_notebook("SOP RAG Assistant", "Topic 5 - LLM / RAG")),
    },
    {
        "slug": "corrosion-segmentation", "title": "Corrosion Type Segmentation",
        "subtitle": "Pixel-level classification of damage",
        "summary": "Segment 15 corrosion classes - general, pitting, crevice, galvanic and preferential weld attack, each at mild, moderate and severe - from inspection photos.",
        "difficulty": "advanced", "hours": 26, "accent": "#8C5B4F", "icon": "layers",
        "heavy": True, "task": "segmentation", "xp": 250,
        "analogy": "Two rust patches can look identical to you and mean completely different repairs. "
                   "You are building the second opinion that never gets tired at 4pm.",
        "steps": ["Inspection photos", "Annotate masks", "Augment", "U-Net training", "IoU per class", "Damage overlay"],
        "lessons": corrosion_lessons,
        "nb": ("corrosion-playground", "Corrosion Segmentation Playground", ComputeTarget.COLAB_GPU, True,
               nf.corrosion_segmentation_notebook),
    },
]



def _seed_demo_deployment(session: Session) -> None:
    """One worked example in the portal, so Deployment and Portal are not empty
    on a fresh install.

    It points at the real Streamlit starter and is scored by the same rubric
    engine as a student submission - nothing is faked, it genuinely passes 5/5.
    """
    from app.services import compliance

    intern = session.exec(select(User).where(User.email == "intern@atlas.id")).first()
    topic = session.exec(
        select(Topic).where(Topic.slug == "predictive-maintenance")).first()
    if not intern or not topic:
        return

    bundle = Path(__file__).resolve().parents[3] / "templates" / "streamlit_starter"
    if not bundle.is_dir():
        return

    deployment = Deployment(
        topic_id=topic.id or 0, user_id=intern.id or 0,
        name="Equipment Failure Predictor",
        slug="equipment-failure-predictor",
        framework=AppFramework.STREAMLIT,
        entrypoint="app.py",
        source_kind="upload",
        bundle_path=str(bundle),
        status=DeploymentStatus.RUNNING,
        url="https://equipment-failure-predictor.demo.atlas.id",
        whimsical_url="https://whimsical.com/atlas-demo",
        published_to_portal=True,
        build_logs="Seeded example. Rebuild from the Deployment tab to redeploy.",
    )
    session.add(deployment)
    session.commit()
    session.refresh(deployment)

    # score it with the real rubric engine
    compliance.evaluate(session, deployment, task_type="classification")
    session.commit()

def seed(session: Session) -> None:
    if session.exec(select(User)).first():
        return

    for email, name, role, password, cohort in USERS:
        session.add(User(email=email, full_name=name, role=role,
                         hashed_password=hash_password(password), cohort=cohort))
    session.commit()

    for order, spec in enumerate(TOPICS):
        topic = Topic(
            slug=spec["slug"], title=spec["title"], subtitle=spec["subtitle"],
            summary=spec["summary"], difficulty=spec["difficulty"],
            estimated_hours=spec["hours"], accent=spec["accent"], icon=spec["icon"],
            heavy_compute=spec["heavy"], task_type=spec["task"], xp_reward=spec["xp"],
            order_index=order,
        )
        session.add(topic)
        session.commit()
        session.refresh(topic)

        lesson_specs = spec.get("lessons")
        lesson_specs = (lesson_specs() if callable(lesson_specs) else lesson_specs) \
            or _intro_lessons(spec["title"], spec["analogy"], spec["steps"])
        for spec_lesson in lesson_specs:
            lesson = Lesson(
                topic_id=topic.id or 0, slug=spec_lesson["slug"], title=spec_lesson["title"],
                hook=spec_lesson["hook"], duration_minutes=spec_lesson["duration_minutes"],
                xp_reward=spec_lesson["xp_reward"], order_index=spec_lesson["order_index"],
            )
            session.add(lesson)
            session.commit()
            session.refresh(lesson)
            for block in spec_lesson["blocks"]:
                block.lesson_id = lesson.id or 0
                session.add(block)
            session.commit()

        slug, title, target, gpu, builder = spec["nb"]
        session.add(Notebook(
            topic_id=topic.id or 0, slug=slug, title=title,
            description=f"Guided playground for {spec['title']}. Bridge helpers stream metrics back to ATLAS.",
            default_target=target, requires_gpu=gpu,
            content_json=json.dumps(builder(), ensure_ascii=False),
            requirements="pandas\nscikit-learn\nnumpy" if not gpu else "torch\ntorchvision\nultralytics",
        ))
        session.commit()

    _seed_demo_deployment(session)
