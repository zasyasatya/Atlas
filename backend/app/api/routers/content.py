"""Topics, lessons and the no-code block CMS."""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException, status
from sqlmodel import delete, func, select

from app.api.deps import CurrentUser, EditorUser, SessionDep
from app.domain.enums import ContentStatus
from app.domain.models import Asset, Lesson, LessonBlock, Notebook, Progress, Topic
from app.domain.schemas import (
    BlockOut,
    LessonIn,
    LessonOut,
    TopicDetail,
    TopicIn,
    TopicOut,
)
from app.services.activity import record

router = APIRouter(prefix="/api", tags=["content"])


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:60] or "item"


def _blocks_for(session, lesson_id: int) -> list[BlockOut]:
    rows = session.exec(
        select(LessonBlock).where(LessonBlock.lesson_id == lesson_id).order_by(LessonBlock.order_index)
    ).all()
    return [BlockOut(id=b.id or 0, block_type=b.block_type, order_index=b.order_index,
                     payload=json.loads(b.payload_json or "{}")) for b in rows]


def _topic_out(session, topic: Topic, user_id: int | None) -> TopicOut:
    lessons = session.exec(select(Lesson).where(Lesson.topic_id == topic.id)).all()
    lesson_ids = [l.id for l in lessons]
    completed = 0
    if user_id and lesson_ids:
        completed = len(session.exec(
            select(Progress).where(Progress.user_id == user_id,
                                   Progress.lesson_id.in_(lesson_ids),
                                   Progress.completed == True)  # noqa: E712
        ).all())
    nb = session.exec(select(func.count()).select_from(Notebook).where(Notebook.topic_id == topic.id)).one()
    ds = session.exec(select(func.count()).select_from(Asset).where(
        Asset.topic_id == topic.id, Asset.kind == "dataset")).one()
    dk = session.exec(select(func.count()).select_from(Asset).where(
        Asset.topic_id == topic.id, Asset.kind == "deck")).one()
    return TopicOut(
        id=topic.id or 0, title=topic.title, slug=topic.slug, subtitle=topic.subtitle,
        summary=topic.summary, difficulty=topic.difficulty, estimated_hours=topic.estimated_hours,
        accent=topic.accent, icon=topic.icon, heavy_compute=topic.heavy_compute,
        task_type=topic.task_type, xp_reward=topic.xp_reward, order_index=topic.order_index,
        status=topic.status, lesson_count=len(lessons), completed_lessons=completed,
        notebook_count=nb, dataset_count=ds, deck_count=dk,
    )


@router.get("/topics", response_model=list[TopicOut])
def list_topics(session: SessionDep, user: CurrentUser) -> list[TopicOut]:
    topics = session.exec(select(Topic).order_by(Topic.order_index)).all()
    return [_topic_out(session, t, user.id) for t in topics]


@router.post("/topics", response_model=TopicOut, status_code=status.HTTP_201_CREATED)
def create_topic(payload: TopicIn, session: SessionDep, user: EditorUser) -> TopicOut:
    topic = Topic(**payload.model_dump())
    topic.slug = payload.slug or slugify(payload.title)
    if session.exec(select(Topic).where(Topic.slug == topic.slug)).first():
        topic.slug = f"{topic.slug}-{session.exec(select(func.count()).select_from(Topic)).one() + 1}"
    session.add(topic)
    session.commit()
    session.refresh(topic)
    record(session, user=user, action="created topic", entity_type="topic",
           entity_id=topic.id, topic_id=topic.id, detail=topic.title)
    return _topic_out(session, topic, user.id)


@router.get("/topics/{slug}", response_model=TopicDetail)
def get_topic(slug: str, session: SessionDep, user: CurrentUser) -> TopicDetail:
    topic = session.exec(select(Topic).where(Topic.slug == slug)).first()
    if not topic:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Topic not found")
    lessons = session.exec(
        select(Lesson).where(Lesson.topic_id == topic.id).order_by(Lesson.order_index)).all()
    done = {p.lesson_id for p in session.exec(
        select(Progress).where(Progress.user_id == user.id, Progress.completed == True)).all()}  # noqa: E712
    base = _topic_out(session, topic, user.id)
    return TopicDetail(**base.model_dump(), lessons=[
        LessonOut(id=l.id or 0, topic_id=l.topic_id, slug=l.slug, title=l.title, hook=l.hook,
                  duration_minutes=l.duration_minutes, xp_reward=l.xp_reward,
                  order_index=l.order_index, status=l.status,
                  blocks=_blocks_for(session, l.id or 0), completed=(l.id in done))
        for l in lessons])


@router.patch("/topics/{topic_id}", response_model=TopicOut)
def update_topic(topic_id: int, payload: TopicIn, session: SessionDep, user: EditorUser) -> TopicOut:
    topic = session.get(Topic, topic_id)
    if not topic:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Topic not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        if key == "slug" and not value:
            continue
        setattr(topic, key, value)
    session.add(topic)
    session.commit()
    session.refresh(topic)
    record(session, user=user, action="updated topic", entity_type="topic",
           entity_id=topic.id, topic_id=topic.id, detail=topic.title)
    return _topic_out(session, topic, user.id)


@router.delete("/topics/{topic_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_topic(topic_id: int, session: SessionDep, user: EditorUser) -> None:
    topic = session.get(Topic, topic_id)
    if not topic:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Topic not found")
    lessons = session.exec(select(Lesson).where(Lesson.topic_id == topic_id)).all()
    for lesson in lessons:
        session.exec(delete(LessonBlock).where(LessonBlock.lesson_id == lesson.id))
    session.exec(delete(Lesson).where(Lesson.topic_id == topic_id))
    session.delete(topic)
    session.commit()
    record(session, user=user, action="deleted topic", entity_type="topic", detail=topic.title)


@router.post("/topics/{topic_id}/lessons", response_model=LessonOut, status_code=201)
def create_lesson(topic_id: int, payload: LessonIn, session: SessionDep, user: EditorUser) -> LessonOut:
    if not session.get(Topic, topic_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Topic not found")
    count = len(session.exec(select(Lesson).where(Lesson.topic_id == topic_id)).all())
    lesson = Lesson(
        topic_id=topic_id, slug=payload.slug or slugify(payload.title), title=payload.title,
        hook=payload.hook, duration_minutes=payload.duration_minutes, xp_reward=payload.xp_reward,
        order_index=payload.order_index or count, status=payload.status,
    )
    session.add(lesson)
    session.commit()
    session.refresh(lesson)
    for i, block in enumerate(payload.blocks):
        session.add(LessonBlock(lesson_id=lesson.id or 0, order_index=block.order_index or i,
                                block_type=block.block_type,
                                payload_json=json.dumps(block.payload, ensure_ascii=False)))
    session.commit()
    record(session, user=user, action="added lesson", entity_type="lesson",
           entity_id=lesson.id, topic_id=topic_id, detail=lesson.title)
    return LessonOut(id=lesson.id or 0, topic_id=topic_id, slug=lesson.slug, title=lesson.title,
                     hook=lesson.hook, duration_minutes=lesson.duration_minutes,
                     xp_reward=lesson.xp_reward, order_index=lesson.order_index,
                     status=lesson.status, blocks=_blocks_for(session, lesson.id or 0))


@router.put("/lessons/{lesson_id}", response_model=LessonOut)
def update_lesson(lesson_id: int, payload: LessonIn, session: SessionDep, user: EditorUser) -> LessonOut:
    lesson = session.get(Lesson, lesson_id)
    if not lesson:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lesson not found")
    lesson.title = payload.title
    lesson.hook = payload.hook
    lesson.duration_minutes = payload.duration_minutes
    lesson.xp_reward = payload.xp_reward
    lesson.status = payload.status
    if payload.slug:
        lesson.slug = payload.slug
    session.add(lesson)
    session.exec(delete(LessonBlock).where(LessonBlock.lesson_id == lesson_id))
    for i, block in enumerate(payload.blocks):
        session.add(LessonBlock(lesson_id=lesson_id, order_index=block.order_index or i,
                                block_type=block.block_type,
                                payload_json=json.dumps(block.payload, ensure_ascii=False)))
    session.commit()
    session.refresh(lesson)
    record(session, user=user, action="edited lesson", entity_type="lesson",
           entity_id=lesson_id, topic_id=lesson.topic_id, detail=lesson.title)
    return LessonOut(id=lesson.id or 0, topic_id=lesson.topic_id, slug=lesson.slug,
                     title=lesson.title, hook=lesson.hook, duration_minutes=lesson.duration_minutes,
                     xp_reward=lesson.xp_reward, order_index=lesson.order_index,
                     status=lesson.status, blocks=_blocks_for(session, lesson_id))


@router.delete("/lessons/{lesson_id}", status_code=204, response_model=None)
def delete_lesson(lesson_id: int, session: SessionDep, user: EditorUser) -> None:
    lesson = session.get(Lesson, lesson_id)
    if not lesson:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lesson not found")
    session.exec(delete(LessonBlock).where(LessonBlock.lesson_id == lesson_id))
    session.delete(lesson)
    session.commit()
    record(session, user=user, action="deleted lesson", entity_type="lesson",
           topic_id=lesson.topic_id, detail=lesson.title)


@router.post("/lessons/{lesson_id}/complete")
def complete_lesson(lesson_id: int, session: SessionDep, user: CurrentUser, score: float = 100.0) -> dict:
    lesson = session.get(Lesson, lesson_id)
    if not lesson:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lesson not found")
    existing = session.exec(select(Progress).where(Progress.user_id == user.id,
                                                   Progress.lesson_id == lesson_id)).first()
    from datetime import datetime, timezone
    if existing:
        existing.completed, existing.score = True, score
        existing.xp_earned = lesson.xp_reward
        existing.completed_at = datetime.now(timezone.utc)
        session.add(existing)
    else:
        session.add(Progress(user_id=user.id or 0, lesson_id=lesson_id, topic_id=lesson.topic_id,
                             completed=True, score=score, xp_earned=lesson.xp_reward,
                             completed_at=datetime.now(timezone.utc)))
    session.commit()
    total_xp = sum(p.xp_earned for p in session.exec(
        select(Progress).where(Progress.user_id == user.id, Progress.completed == True)).all())  # noqa: E712
    return {"ok": True, "xp_earned": lesson.xp_reward, "total_xp": total_xp}


@router.get("/progress/me")
def my_progress(session: SessionDep, user: CurrentUser) -> dict:
    rows = session.exec(select(Progress).where(Progress.user_id == user.id,
                                               Progress.completed == True)).all()  # noqa: E712
    total_lessons = session.exec(select(func.count()).select_from(Lesson).where(
        Lesson.status == ContentStatus.PUBLISHED)).one()
    xp = sum(r.xp_earned for r in rows)
    level = 1 + xp // 200
    return {"completed_lessons": len(rows), "total_lessons": total_lessons, "xp": xp,
            "level": level, "next_level_xp": (level) * 200,
            "by_topic": {str(r.topic_id): 1 for r in rows}}
