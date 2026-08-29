'use client';
import React from 'react';
import { api, Lesson } from '@/lib/api';
import { BLOCK_TYPES, BlockRenderer } from './BlockRenderer';
import { Badge, Button, Field, Input, inputCls, Modal, Select, Textarea } from './UI';
import { IcCheck, IcPlus, IcTrash, IcX } from './Icons';

/** No-code authoring surface. A supervisor composes a lesson from typed blocks. */
export function LessonEditor({ topicId, lesson, onClose, onSaved }: {
  topicId: number; lesson: Lesson | null; onClose: () => void; onSaved: () => void;
}) {
  const [title, setTitle] = React.useState(lesson?.title || '');
  const [hook, setHook] = React.useState(lesson?.hook || '');
  const [minutes, setMinutes] = React.useState(lesson?.duration_minutes ?? 10);
  const [xp, setXp] = React.useState(lesson?.xp_reward ?? 25);
  const [blocks, setBlocks] = React.useState<any[]>(lesson?.blocks?.map((b) => ({ ...b })) || []);
  const [preview, setPreview] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [adding, setAdding] = React.useState(false);

  function addBlock(type: string) {
    const defaults: Record<string, any> = {
      text: { body: 'Write the explanation here. Use **bold**, *italic*, `code` and - bullets.' },
      callout: { tone: 'quest', title: 'Your mission', body: 'Frame the problem in one human sentence.' },
      architecture: { title: 'How it works', nodes: [
        { id: 'n0', label: 'Input data', note: '' },
        { id: 'n1', label: 'Preprocess', note: '' },
        { id: 'n2', label: 'Model', note: '' },
        { id: 'n3', label: 'Output', note: '' }] },
      quiz: { question: 'Ask something that exposes a misconception.', options: ['Option A', 'Option B', 'Option C'], answer: 0, explanation: 'Explain why.' },
      flashcard: { cards: [{ front: 'Term', back: 'Plain-language meaning' }] },
      code: { language: 'python', code: 'print("hello")', caption: '' },
      image: { url: '', caption: '' },
      video: { url: '', caption: '' },
    };
    setBlocks([...blocks, { block_type: type, payload: defaults[type] || {}, order_index: blocks.length }]);
    setAdding(false);
  }

  const update = (i: number, payload: any) =>
    setBlocks(blocks.map((b, j) => (j === i ? { ...b, payload } : b)));
  const remove = (i: number) => setBlocks(blocks.filter((_, j) => j !== i));
  const move = (i: number, dir: number) => {
    const j = i + dir;
    if (j < 0 || j >= blocks.length) return;
    const copy = [...blocks];
    [copy[i], copy[j]] = [copy[j], copy[i]];
    setBlocks(copy.map((b, k) => ({ ...b, order_index: k })));
  };

  async function save() {
    if (!title.trim()) return alert('Title is required');
    setBusy(true);
    try {
      const body = {
        title, hook, duration_minutes: minutes, xp_reward: xp, status: 'published',
        blocks: blocks.map((b, i) => ({ block_type: b.block_type, payload: b.payload, order_index: i })),
      };
      if (lesson?.id) await api.put(`/api/lessons/${lesson.id}`, body);
      else await api.post(`/api/topics/${topicId}/lessons`, body);
      onSaved();
    } catch (e: any) { alert(e.message); } finally { setBusy(false); }
  }

  return (
    <Modal open onClose={onClose} wide
      title={lesson ? 'Edit stage' : 'New stage'}
      subtitle="Compose the lesson from blocks. No code, no codebase access required.">
      <div className="space-y-5 max-h-[68vh] overflow-y-auto pr-1 -mr-1">
        <div className="grid sm:grid-cols-2 gap-3">
          <Field label="Stage title" required>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Stage 1 — Mission Briefing" />
          </Field>
          <Field label="One-line hook">
            <Input value={hook} onChange={(e) => setHook(e.target.value)} placeholder="What problem are we solving?" />
          </Field>
          <Field label="Duration (minutes)"><Input type="number" value={minutes} onChange={(e) => setMinutes(+e.target.value)} /></Field>
          <Field label="XP reward"><Input type="number" value={xp} onChange={(e) => setXp(+e.target.value)} /></Field>
        </div>

        <div className="flex items-center justify-between border-t border-line pt-4">
          <div>
            <span className="text-[13px] font-bold text-ink">Content blocks</span>
            <span className="text-[12px] text-ink-muted ml-2">{blocks.length} block{blocks.length === 1 ? '' : 's'}</span>
          </div>
          <div className="flex gap-1.5">
            <Button size="sm" variant={preview ? 'primary' : 'outline'} onClick={() => setPreview(!preview)}>
              {preview ? 'Editing' : 'Preview'}
            </Button>
            <Button size="sm" icon={<IcPlus size={13} />} onClick={() => setAdding(!adding)}>Add block</Button>
          </div>
        </div>

        {adding && (
          <div className="grid sm:grid-cols-2 gap-2 p-3 rounded-2xl bg-paper-deep border border-line animate-rise">
            {BLOCK_TYPES.map((t) => (
              <button key={t.id} onClick={() => addBlock(t.id)}
                className="text-left px-3.5 py-2.5 rounded-xl bg-white border border-line hover:border-sage-400 hover:bg-sage-50 transition-all">
                <div className="text-[13px] font-bold text-ink">{t.label}</div>
                <div className="text-[11.5px] text-ink-muted mt-0.5">{t.hint}</div>
              </button>
            ))}
          </div>
        )}

        {preview ? (
          <div className="space-y-5 p-5 rounded-2xl bg-paper border border-line">
            {blocks.map((b, i) => <BlockRenderer key={i} block={b} />)}
            {blocks.length === 0 && <div className="text-[13px] text-ink-faint text-center py-6">Nothing to preview.</div>}
          </div>
        ) : (
          <div className="space-y-3">
            {blocks.map((b, i) => (
              <div key={i} className="border border-line rounded-2xl overflow-hidden">
                <div className="flex items-center gap-2 px-3.5 py-2 bg-paper-deep/60 border-b border-line">
                  <Badge tone="sage">{BLOCK_TYPES.find((t) => t.id === b.block_type)?.label || b.block_type}</Badge>
                  <div className="ml-auto flex items-center gap-0.5">
                    <button onClick={() => move(i, -1)} disabled={i === 0} className="p-1.5 rounded-lg text-ink-faint hover:bg-white disabled:opacity-30 text-[11px] font-bold">↑</button>
                    <button onClick={() => move(i, 1)} disabled={i === blocks.length - 1} className="p-1.5 rounded-lg text-ink-faint hover:bg-white disabled:opacity-30 text-[11px] font-bold">↓</button>
                    <button onClick={() => remove(i)} className="p-1.5 rounded-lg text-ink-faint hover:bg-white hover:text-signal-bad"><IcTrash size={13} /></button>
                  </div>
                </div>
                <div className="p-3.5">
                  <BlockForm type={b.block_type} payload={b.payload} onChange={(p: any) => update(i, p)} />
                </div>
              </div>
            ))}
            {blocks.length === 0 && (
              <div className="text-center py-10 border border-dashed border-line-strong rounded-2xl">
                <div className="text-[13.5px] text-ink-muted mb-3">No blocks yet.</div>
                <Button size="sm" variant="outline" icon={<IcPlus size={13} />} onClick={() => setAdding(true)}>Add your first block</Button>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="flex gap-2 pt-4 mt-4 border-t border-line">
        <Button onClick={save} loading={busy} className="flex-1" icon={<IcCheck size={15} />}>
          {lesson ? 'Save stage' : 'Publish stage'}
        </Button>
        <Button variant="outline" onClick={onClose}>Cancel</Button>
      </div>
    </Modal>
  );
}

function BlockForm({ type, payload, onChange }: any) {
  const set = (k: string, v: any) => onChange({ ...payload, [k]: v });

  if (type === 'text') {
    return <Textarea rows={5} value={payload.body || ''} onChange={(e) => set('body', e.target.value)}
      placeholder="Explain it the way you would to a smart person who has never trained a model." />;
  }

  if (type === 'callout') {
    return (
      <div className="space-y-2.5">
        <div className="grid grid-cols-2 gap-2.5">
          <Select value={payload.tone || 'info'} onChange={(e) => set('tone', e.target.value)}>
            <option value="quest">Quest (green)</option><option value="warning">Warning (amber)</option>
            <option value="info">Info (blue)</option><option value="success">Success</option>
          </Select>
          <Input value={payload.title || ''} onChange={(e) => set('title', e.target.value)} placeholder="Box title" />
        </div>
        <Textarea rows={3} value={payload.body || ''} onChange={(e) => set('body', e.target.value)} placeholder="Body text" />
      </div>
    );
  }

  if (type === 'architecture') {
    const nodes = payload.nodes || [];
    const setNode = (i: number, k: string, v: string) =>
      set('nodes', nodes.map((n: any, j: number) => (j === i ? { ...n, [k]: v } : n)));
    return (
      <div className="space-y-2.5">
        <Input value={payload.title || ''} onChange={(e) => set('title', e.target.value)} placeholder="Diagram title" />
        <div className="space-y-2">
          {nodes.map((n: any, i: number) => (
            <div key={i} className="flex gap-2 items-start">
              <span className="text-[11px] font-bold text-ink-faint mt-3 w-7 shrink-0">#{i + 1}</span>
              <div className="flex-1 space-y-1.5">
                <Input value={n.label || ''} onChange={(e) => setNode(i, 'label', e.target.value)} placeholder="Step name" />
                <Input value={n.note || ''} onChange={(e) => setNode(i, 'note', e.target.value)} placeholder="Explanation shown when clicked (optional)" />
              </div>
              <button onClick={() => set('nodes', nodes.filter((_: any, j: number) => j !== i))}
                className="p-2 mt-1 rounded-lg text-ink-faint hover:text-signal-bad"><IcX size={13} /></button>
            </div>
          ))}
        </div>
        <Button size="sm" variant="outline" icon={<IcPlus size={12} />}
          onClick={() => set('nodes', [...nodes, { id: `n${nodes.length}`, label: '', note: '' }])}>
          Add step
        </Button>
      </div>
    );
  }

  if (type === 'quiz') {
    const options = payload.options || [];
    return (
      <div className="space-y-2.5">
        <Textarea rows={2} value={payload.question || ''} onChange={(e) => set('question', e.target.value)} placeholder="Question" />
        {options.map((o: string, i: number) => (
          <div key={i} className="flex gap-2 items-center">
            <button onClick={() => set('answer', i)}
              className={`w-6 h-6 rounded-full text-[10px] font-bold shrink-0 grid place-items-center border transition-all ${
                payload.answer === i ? 'bg-signal-ok border-signal-ok text-white' : 'bg-white border-line text-ink-faint hover:border-sage-400'}`}
              title="Mark as the correct answer">
              {payload.answer === i ? <IcCheck size={11} /> : String.fromCharCode(65 + i)}
            </button>
            <Input value={o} onChange={(e) => set('options', options.map((x: string, j: number) => (j === i ? e.target.value : x)))} />
            <button onClick={() => set('options', options.filter((_: any, j: number) => j !== i))}
              className="p-1.5 rounded-lg text-ink-faint hover:text-signal-bad"><IcX size={13} /></button>
          </div>
        ))}
        <div className="flex gap-2">
          <Button size="sm" variant="outline" icon={<IcPlus size={12} />} onClick={() => set('options', [...options, ''])}>Add option</Button>
          <span className="text-[11.5px] text-ink-faint self-center">click a letter to mark the correct answer</span>
        </div>
        <Textarea rows={2} value={payload.explanation || ''} onChange={(e) => set('explanation', e.target.value)} placeholder="Explanation shown after answering" />
      </div>
    );
  }

  if (type === 'flashcard') {
    const cards = payload.cards || [];
    return (
      <div className="space-y-2">
        {cards.map((c: any, i: number) => (
          <div key={i} className="flex gap-2">
            <Input value={c.front || ''} onChange={(e) => set('cards', cards.map((x: any, j: number) => (j === i ? { ...x, front: e.target.value } : x)))} placeholder="Term" />
            <Input value={c.back || ''} onChange={(e) => set('cards', cards.map((x: any, j: number) => (j === i ? { ...x, back: e.target.value } : x)))} placeholder="Plain meaning" />
            <button onClick={() => set('cards', cards.filter((_: any, j: number) => j !== i))}
              className="p-2 rounded-lg text-ink-faint hover:text-signal-bad shrink-0"><IcX size={13} /></button>
          </div>
        ))}
        <Button size="sm" variant="outline" icon={<IcPlus size={12} />} onClick={() => set('cards', [...cards, { front: '', back: '' }])}>Add card</Button>
      </div>
    );
  }

  if (type === 'code') {
    return (
      <div className="space-y-2.5">
        <div className="grid grid-cols-2 gap-2.5">
          <Input value={payload.language || 'python'} onChange={(e) => set('language', e.target.value)} placeholder="Language" />
          <Input value={payload.caption || ''} onChange={(e) => set('caption', e.target.value)} placeholder="Caption (optional)" />
        </div>
        <textarea rows={6} value={payload.code || ''} onChange={(e) => set('code', e.target.value)}
          className={`${inputCls} mono text-[12.5px]`} placeholder="Paste the snippet" />
      </div>
    );
  }

  return (
    <div className="space-y-2.5">
      <Input value={payload.url || ''} onChange={(e) => set('url', e.target.value)}
        placeholder={type === 'video' ? 'Embed URL (YouTube/Drive)' : 'Image URL'} />
      <Input value={payload.caption || ''} onChange={(e) => set('caption', e.target.value)} placeholder="Caption" />
    </div>
  );
}
