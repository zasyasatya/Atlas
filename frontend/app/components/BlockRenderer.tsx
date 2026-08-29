'use client';
import React from 'react';
import { Badge, Button, Card } from './UI';
import { IcAlert, IcCheck, IcCode, IcImage, IcSpark, IcTarget, IcX } from './Icons';

/** Renders one CMS-authored lesson block. Supervisors never write code for these. */
export function BlockRenderer({ block }: { block: any }) {
  const p = block.payload || {};
  switch (block.block_type) {
    case 'text': return <TextBlock body={p.body} />;
    case 'callout': return <CalloutBlock {...p} />;
    case 'architecture': return <ArchitectureBlock {...p} />;
    case 'quiz': return <QuizBlock {...p} />;
    case 'flashcard': return <FlashcardBlock cards={p.cards || []} />;
    case 'code': return <CodeBlock {...p} />;
    case 'image': return <ImageBlock {...p} />;
    case 'video': return <VideoBlock {...p} />;
    default: return null;
  }
}

/** Minimal, dependency-free markdown-ish inline formatting. */
function rich(text: string) {
  if (!text) return null;
  const parts = String(text).split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g);
  return parts.map((s, i) => {
    if (s.startsWith('**') && s.endsWith('**')) return <strong key={i}>{s.slice(2, -2)}</strong>;
    if (s.startsWith('*') && s.endsWith('*')) return <em key={i}>{s.slice(1, -1)}</em>;
    if (s.startsWith('`') && s.endsWith('`')) return <code key={i}>{s.slice(1, -1)}</code>;
    return <React.Fragment key={i}>{s}</React.Fragment>;
  });
}

function TextBlock({ body }: { body: string }) {
  const paras = String(body || '').split('\n').filter(Boolean);
  return (
    <div className="prose-atlas text-[15px]">
      {paras.map((line, i) =>
        line.trim().startsWith('- ') ? (
          <div key={i} className="flex gap-2.5 mb-1.5">
            <span className="text-sage-500 mt-1.5 shrink-0 w-1 h-1 rounded-full bg-sage-500" />
            <span className="text-ink-soft leading-relaxed">{rich(line.replace(/^-\s*/, ''))}</span>
          </div>
        ) : <p key={i}>{rich(line)}</p>
      )}
    </div>
  );
}

function CalloutBlock({ tone = 'info', title, body }: any) {
  const styles: Record<string, { bg: string; border: string; icon: JSX.Element; label: string }> = {
    quest: { bg: 'bg-sage-50', border: 'border-sage-200', icon: <IcTarget size={15} />, label: 'text-sage-800' },
    warning: { bg: 'bg-[#FBF3E2]', border: 'border-[#EEDFBE]', icon: <IcAlert size={15} />, label: 'text-[#8A6420]' },
    info: { bg: 'bg-[#EAF1F4]', border: 'border-[#CFDFE6]', icon: <IcSpark size={15} />, label: 'text-[#3C6373]' },
    success: { bg: 'bg-[#EAF3EC]', border: 'border-[#CFE3D4]', icon: <IcCheck size={15} />, label: 'text-[#33663F]' },
  };
  const s = styles[tone] || styles.info;
  return (
    <div className={`${s.bg} border ${s.border} rounded-2xl p-4 sm:p-5`}>
      <div className={`flex items-center gap-2 font-bold text-[13px] mb-2 ${s.label}`}>
        {s.icon}{title}
      </div>
      <div className="text-[14.5px] text-ink-soft leading-relaxed">{rich(body)}</div>
    </div>
  );
}

/** The "explain the AI architecture to a beginner" diagram. */
function ArchitectureBlock({ title, nodes = [], edges = [] }: any) {
  const [focus, setFocus] = React.useState<number | null>(null);
  return (
    <div className="border border-line rounded-2xl overflow-hidden bg-white">
      <div className="px-5 py-3.5 border-b border-line bg-paper-deep/50 flex items-center justify-between">
        <span className="text-[13px] font-bold text-ink">{title || 'How it works'}</span>
        <span className="text-[11px] text-ink-faint">tap a step</span>
      </div>
      <div className="p-5 dot-canvas">
        <div className="flex flex-wrap items-stretch gap-2">
          {nodes.map((n: any, i: number) => (
            <React.Fragment key={n.id || i}>
              <button onClick={() => setFocus(focus === i ? null : i)}
                className={`flex-1 min-w-[112px] text-left px-3.5 py-3 rounded-xl border transition-all duration-150 ${
                  focus === i ? 'bg-sage-600 border-sage-600 text-white shadow-soft scale-[1.02]'
                              : 'bg-white border-line hover:border-sage-300 hover:bg-sage-50'}`}>
                <div className={`text-[10px] font-bold mb-1 ${focus === i ? 'text-sage-100' : 'text-ink-faint'}`}>
                  STEP {i + 1}
                </div>
                <div className={`text-[13px] font-bold leading-tight ${focus === i ? 'text-white' : 'text-ink'}`}>
                  {n.label}
                </div>
              </button>
              {i < nodes.length - 1 && (
                <div className="hidden sm:flex items-center text-line-strong shrink-0">
                  <svg width="16" height="10" viewBox="0 0 16 10" fill="none">
                    <path d="M0 5h13M10 1.5 13.5 5 10 8.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </div>
              )}
            </React.Fragment>
          ))}
        </div>
        {focus !== null && (
          <div className="mt-3.5 px-4 py-3 rounded-xl bg-sage-50 border border-sage-200 animate-rise">
            <div className="text-[13px] font-bold text-sage-800 mb-0.5">{nodes[focus].label}</div>
            <div className="text-[13px] text-ink-soft leading-relaxed">
              {nodes[focus].note || `This stage takes the output of the previous step and prepares it for step ${focus + 2 <= nodes.length ? focus + 2 : 'delivery'}. If your final metric looks wrong, inspect what leaves this box.`}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function QuizBlock({ question, options = [], answer = 0, explanation }: any) {
  const [picked, setPicked] = React.useState<number | null>(null);
  const done = picked !== null;
  return (
    <div className="border border-line rounded-2xl overflow-hidden bg-white">
      <div className="px-5 py-3.5 border-b border-line bg-paper-deep/50 flex items-center gap-2">
        <IcTarget size={14} className="text-sage-600" />
        <span className="text-[13px] font-bold">Checkpoint</span>
      </div>
      <div className="p-5">
        <div className="text-[15px] font-semibold text-ink mb-4 leading-snug">{question}</div>
        <div className="space-y-2">
          {options.map((opt: string, i: number) => {
            const correct = i === answer;
            const chosen = picked === i;
            let cls = 'border-line hover:border-sage-300 hover:bg-sage-50';
            if (done && correct) cls = 'border-signal-ok bg-[#EAF3EC]';
            else if (done && chosen) cls = 'border-signal-bad bg-[#FAEBE8]';
            else if (done) cls = 'border-line opacity-55';
            return (
              <button key={i} disabled={done} onClick={() => setPicked(i)}
                className={`w-full flex items-center gap-3 text-left px-4 py-3 rounded-xl border transition-all ${cls}`}>
                <span className={`w-5 h-5 rounded-full grid place-items-center text-[10px] font-bold shrink-0 ${
                  done && correct ? 'bg-signal-ok text-white' : done && chosen ? 'bg-signal-bad text-white' : 'bg-paper-deep text-ink-muted'}`}>
                  {done && correct ? <IcCheck size={11} /> : done && chosen ? <IcX size={11} /> : String.fromCharCode(65 + i)}
                </span>
                <span className="text-[14px] text-ink-soft">{opt}</span>
              </button>
            );
          })}
        </div>
        {done && (
          <div className="mt-4 px-4 py-3 rounded-xl bg-paper-deep animate-rise">
            <div className={`text-[13px] font-bold mb-1 ${picked === answer ? 'text-signal-ok' : 'text-signal-warn'}`}>
              {picked === answer ? 'Correct' : 'Not quite'}
            </div>
            <div className="text-[13px] text-ink-soft leading-relaxed">{explanation}</div>
          </div>
        )}
      </div>
    </div>
  );
}

function FlashcardBlock({ cards }: { cards: any[] }) {
  const [flipped, setFlipped] = React.useState<Record<number, boolean>>({});
  return (
    <div className="grid sm:grid-cols-2 gap-3">
      {cards.map((c, i) => (
        <button key={i} onClick={() => setFlipped({ ...flipped, [i]: !flipped[i] })}
          className="text-left p-4 rounded-2xl border border-line bg-white hover:border-sage-300 hover:shadow-soft transition-all min-h-[92px]">
          <div className="eyebrow mb-1.5">{flipped[i] ? 'MEANING' : 'TERM'}</div>
          <div className={`text-[14px] leading-snug ${flipped[i] ? 'text-ink-soft' : 'font-bold text-ink'}`}>
            {flipped[i] ? c.back : c.front}
          </div>
        </button>
      ))}
    </div>
  );
}

function CodeBlock({ code, language = 'python', caption }: any) {
  return (
    <div className="rounded-2xl overflow-hidden border border-line">
      <div className="flex items-center gap-2 px-4 py-2 bg-ink text-white">
        <IcCode size={13} />
        <span className="text-[11px] font-semibold">{language}</span>
        {caption && <span className="text-[11px] text-white/55 ml-auto">{caption}</span>}
      </div>
      <pre className="bg-[#161A13] text-[#DCE5DA] p-4 overflow-x-auto text-[12.5px] leading-relaxed mono">
        <code>{code}</code>
      </pre>
    </div>
  );
}

function ImageBlock({ url, caption, alt }: any) {
  return (
    <figure>
      {url ? (
        <img src={url} alt={alt || caption || ''} className="w-full rounded-2xl border border-line" />
      ) : (
        <div className="w-full aspect-[16/7] rounded-2xl border border-line bg-paper-deep grid place-items-center text-ink-faint">
          <IcImage size={26} />
        </div>
      )}
      {caption && <figcaption className="text-[12px] text-ink-muted mt-2 text-center">{caption}</figcaption>}
    </figure>
  );
}

function VideoBlock({ url, caption }: any) {
  return (
    <div>
      <div className="aspect-video rounded-2xl overflow-hidden border border-line bg-ink">
        {url ? <iframe src={url} className="w-full h-full" allowFullScreen title={caption || 'video'} />
             : <div className="w-full h-full grid place-items-center text-white/40 text-[13px]">No video URL</div>}
      </div>
      {caption && <div className="text-[12px] text-ink-muted mt-2 text-center">{caption}</div>}
    </div>
  );
}

export const BLOCK_TYPES = [
  { id: 'text', label: 'Text', hint: 'Paragraphs. **bold**, *italic*, `code`, - bullets' },
  { id: 'callout', label: 'Callout', hint: 'Highlighted box: quest, warning, info, success' },
  { id: 'architecture', label: 'Architecture diagram', hint: 'Clickable pipeline steps' },
  { id: 'quiz', label: 'Quiz checkpoint', hint: 'Multiple choice with explanation' },
  { id: 'flashcard', label: 'Flashcards', hint: 'Flip cards for jargon' },
  { id: 'code', label: 'Code sample', hint: 'Syntax-styled snippet' },
  { id: 'image', label: 'Image', hint: 'Diagram or screenshot by URL' },
  { id: 'video', label: 'Video embed', hint: 'YouTube or Drive embed URL' },
];
