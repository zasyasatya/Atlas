'use client';
import Link from 'next/link';
import React from 'react';
import { api, auth, Topic } from '@/lib/api';
import { Page, PageHeader, Shell } from '../components/Shell';
import { Badge, Button, Card, Field, Input, Modal, Progress, Select, Skeleton, Textarea, useToast } from '../components/UI';
import { IcArrowRight, IcBook, IcClock, IcGpu, IcPlus, ICON_MAP, IcSpark } from '../components/Icons';

const ICON_CHOICES = ['activity','scan','file-text','trending-up','message-square','layers','sparkles','database','rocket','target','flask'];
const ACCENTS = ['#5B8C6E','#3F6B52','#4F7D8C','#8C7A4F','#6B5B8C','#8C5B4F'];

export default function Curriculum() {
  const [topics, setTopics] = React.useState<Topic[] | null>(null);
  const [open, setOpen] = React.useState(false);
  const { show, node } = useToast();
  const canEdit = auth.canEdit();

  const load = React.useCallback(() => api.get<Topic[]>('/api/topics').then(setTopics).catch(() => setTopics([])), []);
  React.useEffect(() => { load(); }, [load]);

  return (
    <Shell>
      <PageHeader eyebrow="Curriculum" title="Learn the architecture"
        subtitle="Every topic is a short game: a briefing that frames the problem, a blueprint of the pipeline, then a boss fight that forces you to defend your numbers."
        actions={canEdit && <Button icon={<IcPlus size={15} />} onClick={() => setOpen(true)}>New topic</Button>} />

      <Page>
        {!topics && <div className="grid md:grid-cols-2 gap-4">{[0,1,2,3].map(i => <Skeleton key={i} className="h-44" />)}</div>}
        <div className="grid md:grid-cols-2 gap-4">
          {topics?.map((t, idx) => {
            const Icon = ICON_MAP[t.icon] || IcSpark;
            const pct = Math.round((t.completed_lessons / Math.max(t.lesson_count, 1)) * 100);
            return (
              <Link key={t.id} href={`/curriculum/view?slug=${t.slug}`}>
                <Card hover className="p-5 h-full flex flex-col group">
                  <div className="flex items-start gap-3.5 mb-3.5">
                    <div className="w-11 h-11 rounded-2xl grid place-items-center shrink-0 border"
                      style={{ background: `${t.accent}14`, borderColor: `${t.accent}2b`, color: t.accent }}>
                      <Icon size={20} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="eyebrow mb-1">TOPIC {String(idx + 1).padStart(2, '0')}</div>
                      <h3 className="text-[17px] font-extrabold tracking-[-0.02em] text-ink leading-tight">{t.title}</h3>
                      <p className="text-[12.5px] text-ink-muted mt-0.5">{t.subtitle}</p>
                    </div>
                  </div>
                  <p className="text-[13.5px] text-ink-soft leading-relaxed flex-1 mb-4">{t.summary}</p>
                  <div className="flex flex-wrap items-center gap-1.5 mb-3.5">
                    <Badge tone={t.difficulty === 'advanced' ? 'bad' : t.difficulty === 'intermediate' ? 'warn' : 'ok'}>
                      {t.difficulty}
                    </Badge>
                    <Badge><IcClock size={10} /> {t.estimated_hours}h</Badge>
                    <Badge tone="sage">{t.lesson_count} lessons</Badge>
                    {t.heavy_compute && <Badge tone="info"><IcGpu size={10} /> GPU</Badge>}
                    <Badge tone="neutral">{t.task_type}</Badge>
                  </div>
                  <div className="flex items-center gap-3">
                    <Progress value={pct} tone={pct === 100 ? 'ok' : 'sage'} height={5} />
                    <span className="text-[11px] font-bold text-ink-muted tabular-nums shrink-0">{pct}%</span>
                    <IcArrowRight size={15} className="text-ink-faint group-hover:text-sage-600 group-hover:translate-x-0.5 transition-all shrink-0" />
                  </div>
                </Card>
              </Link>
            );
          })}
        </div>
      </Page>

      <TopicModal open={open} onClose={() => setOpen(false)} onSaved={() => { setOpen(false); load(); show('Topic created'); }} />
      {node}
    </Shell>
  );
}

export function TopicModal({ open, onClose, onSaved, initial }: any) {
  const [f, setF] = React.useState<any>(initial || {
    title: '', subtitle: '', summary: '', difficulty: 'beginner', estimated_hours: 8,
    accent: ACCENTS[0], icon: 'sparkles', heavy_compute: false, task_type: 'classification', xp_reward: 100,
  });
  const [busy, setBusy] = React.useState(false);
  React.useEffect(() => { if (initial) setF(initial); }, [initial]);
  const set = (k: string, v: any) => setF((p: any) => ({ ...p, [k]: v }));

  async function save() {
    setBusy(true);
    try {
      if (initial?.id) await api.patch(`/api/topics/${initial.id}`, f);
      else await api.post('/api/topics', f);
      onSaved();
    } catch (e: any) { alert(e.message); } finally { setBusy(false); }
  }

  return (
    <Modal open={open} onClose={onClose} title={initial?.id ? 'Edit topic' : 'New topic'}
      subtitle="Interns see this as a track on the curriculum board.">
      <div className="space-y-4">
        <Field label="Title" required><Input value={f.title} onChange={(e) => set('title', e.target.value)} placeholder="e.g. Corrosion Type Segmentation" /></Field>
        <Field label="Subtitle"><Input value={f.subtitle} onChange={(e) => set('subtitle', e.target.value)} placeholder="Pixel-level classification of damage" /></Field>
        <Field label="Summary" hint="one or two sentences">
          <Textarea rows={2} value={f.summary} onChange={(e) => set('summary', e.target.value)} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Difficulty">
            <Select value={f.difficulty} onChange={(e) => set('difficulty', e.target.value)}>
              <option value="beginner">Beginner</option><option value="intermediate">Intermediate</option><option value="advanced">Advanced</option>
            </Select>
          </Field>
          <Field label="Task type" hint="drives the rubric">
            <Select value={f.task_type} onChange={(e) => set('task_type', e.target.value)}>
              <option value="classification">Classification</option><option value="regression">Regression</option>
              <option value="forecasting">Forecasting</option><option value="segmentation">Segmentation</option>
              <option value="extraction">Extraction</option>
            </Select>
          </Field>
          <Field label="Estimated hours"><Input type="number" value={f.estimated_hours} onChange={(e) => set('estimated_hours', +e.target.value)} /></Field>
          <Field label="XP reward"><Input type="number" value={f.xp_reward} onChange={(e) => set('xp_reward', +e.target.value)} /></Field>
        </div>
        <Field label="Icon">
          <div className="flex flex-wrap gap-1.5">
            {ICON_CHOICES.map((ic) => {
              const I = ICON_MAP[ic] || IcSpark;
              return (
                <button key={ic} type="button" onClick={() => set('icon', ic)}
                  className={`w-9 h-9 rounded-xl grid place-items-center border transition-all ${
                    f.icon === ic ? 'bg-sage-600 border-sage-600 text-white' : 'bg-white border-line text-ink-muted hover:border-sage-300'}`}>
                  <I size={16} />
                </button>
              );
            })}
          </div>
        </Field>
        <Field label="Accent colour">
          <div className="flex gap-1.5">
            {ACCENTS.map((a) => (
              <button key={a} type="button" onClick={() => set('accent', a)}
                className={`w-9 h-9 rounded-xl border-2 transition-all ${f.accent === a ? 'border-ink scale-105' : 'border-transparent'}`}
                style={{ background: a }} />
            ))}
          </div>
        </Field>
        <label className="flex items-center gap-2.5 cursor-pointer">
          <input type="checkbox" checked={f.heavy_compute} onChange={(e) => set('heavy_compute', e.target.checked)}
            className="w-4 h-4 rounded accent-sage-600" />
          <span className="text-[13px] text-ink-soft">
            <strong className="text-ink">Heavy compute</strong> — notebooks in this topic require a GPU target
          </span>
        </label>
        <div className="flex gap-2 pt-2">
          <Button onClick={save} loading={busy} className="flex-1">{initial?.id ? 'Save changes' : 'Create topic'}</Button>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
        </div>
      </div>
    </Modal>
  );
}
