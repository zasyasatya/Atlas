'use client';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import React, { Suspense } from 'react';
import { api, auth, Lesson, TopicDetail } from '@/lib/api';
import { BlockRenderer } from '../../components/BlockRenderer';
import { LessonEditor } from '../../components/LessonEditor';
import { Page, Shell } from '../../components/Shell';
import { Badge, Button, Card, Empty, Progress, Skeleton, useToast } from '../../components/UI';
import {
  IcArrowLeft, IcArrowRight, IcBook, IcCheck, IcClock, IcDatabase, IcEdit,
  IcFlask, IcGpu, IcPlus, ICON_MAP, IcRocket, IcSpark, IcTrash, IcTrophy,
} from '../../components/Icons';

export default function TopicPage() {
  return <Suspense fallback={null}><TopicView /></Suspense>;
}

function TopicView() {
  const searchParams = useSearchParams();
  const slug = searchParams.get('slug') || '';
  const router = useRouter();
  const { show, node } = useToast();
  const [topic, setTopic] = React.useState<TopicDetail | null>(null);
  const [activeId, setActiveId] = React.useState<number | null>(null);
  const [editing, setEditing] = React.useState<Lesson | 'new' | null>(null);
  const canEdit = auth.canEdit();

  const load = React.useCallback(async () => {
    const t = await api.get<TopicDetail>(`/api/topics/${slug}`);
    setTopic(t);
    setActiveId((prev) => prev ?? (t.lessons.find((l) => !l.completed)?.id ?? t.lessons[0]?.id ?? null));
  }, [slug]);

  React.useEffect(() => { load().catch(() => {}); }, [load]);

  if (!topic) {
    return <Shell><Page><Skeleton className="h-64" /></Page></Shell>;
  }

  const Icon = ICON_MAP[topic.icon] || IcSpark;
  const active = topic.lessons.find((l) => l.id === activeId) || null;
  const pct = Math.round((topic.completed_lessons / Math.max(topic.lesson_count, 1)) * 100);
  const idx = topic.lessons.findIndex((l) => l.id === activeId);

  async function complete(lesson: Lesson) {
    await api.post(`/api/lessons/${lesson.id}/complete`);
    show(`+${lesson.xp_reward} XP — ${lesson.title} complete`);
    const next = topic!.lessons[idx + 1];
    await load();
    if (next) setActiveId(next.id);
  }

  async function removeLesson(lesson: Lesson) {
    if (!confirm(`Delete "${lesson.title}"?`)) return;
    await api.del(`/api/lessons/${lesson.id}`);
    setActiveId(null);
    await load();
    show('Lesson deleted');
  }

  return (
    <Shell>
      {/* topic hero, styled after the reference screenshot */}
      <div className="border-b border-line bg-gradient-to-b from-white to-paper">
        <div className="grid-canvas">
          <div className="max-w-[1180px] mx-auto px-5 sm:px-8 py-7">
            <Link href="/curriculum" className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-ink-soft hover:text-ink mb-6 px-2.5 py-1.5 -ml-2.5 rounded-lg border border-transparent hover:border-line hover:bg-white transition-all">
              <IcArrowLeft size={14} /> Curriculum
            </Link>
            <div className="flex flex-wrap items-start justify-between gap-6">
              <div className="min-w-0 flex-1">
                <div className="eyebrow mb-2.5">
                  {topic.difficulty.toUpperCase()} — {topic.estimated_hours}H — {topic.task_type.toUpperCase()}
                </div>
                <div className="flex items-center gap-3.5 mb-3">
                  <div className="w-12 h-12 rounded-2xl grid place-items-center shrink-0 border"
                    style={{ background: `${topic.accent}14`, borderColor: `${topic.accent}2b`, color: topic.accent }}>
                    <Icon size={22} />
                  </div>
                  <div>
                    <h1 className="text-[32px] sm:text-[40px] font-extrabold tracking-[-0.038em] leading-[1.02] text-ink">
                      {topic.title}
                    </h1>
                    <div className="text-[14px] text-ink-muted mt-0.5">{topic.subtitle}</div>
                  </div>
                </div>
                <p className="text-[16px] sm:text-[18px] text-ink-soft leading-relaxed max-w-2xl">{topic.summary}</p>
              </div>
              <div className="flex flex-col gap-2 shrink-0">
                <Link href={`/playground?topic=${topic.id}`}>
                  <Button variant="outline" className="w-full" icon={<IcFlask size={15} />}>Playground</Button>
                </Link>
                <Link href={`/datasets?topic=${topic.id}`}>
                  <Button variant="outline" className="w-full" icon={<IcDatabase size={15} />}>Datasets</Button>
                </Link>
                <Link href={`/deployment?topic=${topic.id}`}>
                  <Button className="w-full" icon={<IcRocket size={15} />}>Deploy app</Button>
                </Link>
              </div>
            </div>
            <div className="flex items-center gap-3 mt-6 max-w-md">
              <Progress value={pct} tone={pct === 100 ? 'ok' : 'sage'} />
              <span className="text-[12px] font-bold text-ink-muted tabular-nums whitespace-nowrap">
                {topic.completed_lessons}/{topic.lesson_count} stages
              </span>
            </div>
          </div>
        </div>
      </div>

      <Page>
        <div className="grid lg:grid-cols-[268px,1fr] gap-6">
          {/* stage list */}
          <div className="space-y-2">
            <div className="flex items-center justify-between px-1 mb-1">
              <span className="eyebrow">Stages</span>
              {canEdit && (
                <button onClick={() => setEditing('new')} className="text-[11.5px] font-bold text-sage-700 hover:text-sage-800 flex items-center gap-1">
                  <IcPlus size={12} /> Add
                </button>
              )}
            </div>
            {topic.lessons.map((l, i) => (
              <button key={l.id} onClick={() => setActiveId(l.id)}
                className={`w-full text-left px-3.5 py-3 rounded-xl border transition-all group ${
                  activeId === l.id ? 'bg-white border-sage-400 shadow-soft' : 'bg-white/60 border-line hover:border-sage-300 hover:bg-white'}`}>
                <div className="flex items-center gap-2.5">
                  <span className={`w-6 h-6 rounded-lg grid place-items-center text-[11px] font-bold shrink-0 ${
                    l.completed ? 'bg-signal-ok text-white' : activeId === l.id ? 'bg-sage-600 text-white' : 'bg-paper-deep text-ink-muted'}`}>
                    {l.completed ? <IcCheck size={12} /> : i + 1}
                  </span>
                  <span className={`text-[13px] font-bold leading-tight flex-1 ${activeId === l.id ? 'text-ink' : 'text-ink-soft'}`}>
                    {l.title}
                  </span>
                </div>
                <div className="flex items-center gap-2 mt-1.5 pl-8.5 text-[11px] text-ink-faint">
                  <IcClock size={10} /> {l.duration_minutes}m
                  <span>·</span>
                  <IcTrophy size={10} /> {l.xp_reward} XP
                </div>
              </button>
            ))}
            {topic.lessons.length === 0 && (
              <div className="text-[12.5px] text-ink-faint px-1 py-4">
                No stages yet.{canEdit && ' Use "Add" to author the first one.'}
              </div>
            )}
          </div>

          {/* lesson body */}
          <div>
            {!active ? (
              <Card>
                <Empty icon={<IcBook size={20} />} title="No stage selected"
                  body={canEdit ? 'Author your first stage with the block editor — no code required.' : 'Your supervisor has not published content for this topic yet.'}
                  action={canEdit && <Button size="sm" icon={<IcPlus size={14} />} onClick={() => setEditing('new')}>Add stage</Button>} />
              </Card>
            ) : (
              <Card className="overflow-hidden">
                <div className="px-6 py-5 border-b border-line flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="eyebrow mb-1.5">STAGE {idx + 1} OF {topic.lessons.length}</div>
                    <h2 className="text-[22px] font-extrabold tracking-[-0.025em] text-ink leading-tight">{active.title}</h2>
                    {active.hook && <p className="text-[14px] text-ink-soft mt-1">{active.hook}</p>}
                  </div>
                  {canEdit && (
                    <div className="flex gap-1 shrink-0">
                      <button onClick={() => setEditing(active)} className="p-2 rounded-lg text-ink-faint hover:bg-paper-deep hover:text-ink transition-colors" title="Edit">
                        <IcEdit size={15} />
                      </button>
                      <button onClick={() => removeLesson(active)} className="p-2 rounded-lg text-ink-faint hover:bg-[#FAEBE8] hover:text-signal-bad transition-colors" title="Delete">
                        <IcTrash size={15} />
                      </button>
                    </div>
                  )}
                </div>

                <div className="p-6 space-y-5">
                  {active.blocks.length === 0 && (
                    <div className="text-[13.5px] text-ink-faint py-6 text-center">This stage has no content blocks yet.</div>
                  )}
                  {active.blocks.map((b, i) => <BlockRenderer key={b.id ?? i} block={b} />)}
                </div>

                <div className="px-6 py-4 border-t border-line bg-paper-deep/40 flex items-center justify-between gap-3">
                  <Button variant="ghost" size="sm" disabled={idx <= 0}
                    onClick={() => setActiveId(topic.lessons[idx - 1].id)} icon={<IcArrowLeft size={14} />}>
                    Previous
                  </Button>
                  <div className="flex items-center gap-2">
                    {active.completed ? (
                      <>
                        <Badge tone="ok"><IcCheck size={10} /> Completed</Badge>
                        {idx < topic.lessons.length - 1 && (
                          <Button size="sm" onClick={() => setActiveId(topic.lessons[idx + 1].id)} icon={<IcArrowRight size={14} />}>
                            Next stage
                          </Button>
                        )}
                      </>
                    ) : (
                      <Button size="sm" onClick={() => complete(active)} icon={<IcCheck size={14} />}>
                        Complete · +{active.xp_reward} XP
                      </Button>
                    )}
                  </div>
                </div>
              </Card>
            )}
          </div>
        </div>
      </Page>

      {editing && (
        <LessonEditor topicId={topic.id} lesson={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={async () => { setEditing(null); await load(); show('Content saved'); }} />
      )}
      {node}
    </Shell>
  );
}
