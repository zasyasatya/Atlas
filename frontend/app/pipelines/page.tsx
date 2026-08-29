'use client';
/**
 * Reference pipeline browser.
 *
 * Stage 6 of the corrosion track tells an intern to open
 * `templates/corrosion_unet/app.py`. Until now that path only existed in the
 * git repository, so anyone working purely through the platform hit a dead end
 * - which is exactly the "materi tidak bisa diakses" report. This page serves
 * the same folder over the API: browse it, read it, download the zip.
 */
import React, { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api';
import { Page, PageHeader, Shell } from '../components/Shell';
import { Badge, Button, Card, Empty, Skeleton, useToast } from '../components/UI';
import { IcCode, IcDownload, IcFileText, IcFlask, IcRocket } from '../components/Icons';

type PipelineFile = { path: string; size: number; language: string };
type Pipeline = {
  slug: string; title: string; summary: string; framework: string;
  topic_slug: string | null; entrypoint: string; highlights: string[];
  file_count: number; total_bytes: number; available: boolean;
  files?: PipelineFile[];
};

const kb = (n: number) => (n < 1024 ? `${n} B` : `${(n / 1024).toFixed(1)} KB`);

const ICONS: Record<string, any> = {
  'corrosion-unet': IcFlask, 'streamlit-starter': IcRocket, 'gradio-starter': IcRocket,
};

export default function PipelinesPage() {
  return <Suspense fallback={null}><Pipelines /></Suspense>;
}

function Pipelines() {
  const params = useSearchParams();
  const wanted = params.get('slug');
  const [list, setList] = React.useState<Pipeline[] | null>(null);
  const [active, setActive] = React.useState<Pipeline | null>(null);
  const [path, setPath] = React.useState<string | null>(null);
  const [file, setFile] = React.useState<{ content: string; language: string } | null>(null);
  const { show, node } = useToast();

  React.useEffect(() => {
    api.get<Pipeline[]>('/api/pipelines').then((rows) => {
      setList(rows);
      const first = rows.find((r) => r.slug === wanted) || rows[0];
      if (first) open(first.slug);
    }).catch(() => setList([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wanted]);

  const open = (slug: string) => {
    setActive(null); setFile(null); setPath(null);
    api.get<Pipeline>(`/api/pipelines/${slug}`).then((p) => {
      setActive(p);
      const entry = p.files?.find((f) => f.path === p.entrypoint) || p.files?.[0];
      if (entry) view(slug, entry.path);
    }).catch(() => show('Could not load pipeline', 'bad'));
  };

  const view = (slug: string, filePath: string) => {
    setPath(filePath); setFile(null);
    api.get<{ content: string; language: string }>(
      `/api/pipelines/${slug}/file?path=${encodeURIComponent(filePath)}`)
      .then(setFile).catch(() => show('Could not read file', 'bad'));
  };

  return (
    <Shell>
      <PageHeader eyebrow="Reference code" title="Pipeline library"
        subtitle="Complete, working implementations you can read end to end. This is the code the lessons point at - browse it here, or download the folder and run it yourself." />

      <Page>
        {!list && <Skeleton className="h-64" />}
        {list && list.length === 0 && (
          <Empty icon={<IcCode size={20} />} title="No pipelines available"
            body="Reference pipelines appear here once a supervisor assigns you the matching topic." />
        )}

        {list && list.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-4">
            {list.map((p) => {
              const Icon = ICONS[p.slug] || IcCode;
              const on = active?.slug === p.slug;
              return (
                <button key={p.slug} onClick={() => open(p.slug)}
                  className={`flex items-center gap-2 px-3.5 py-2 rounded-xl border text-[12.5px] font-semibold transition-colors ${
                    on ? 'bg-sage-50 border-sage-200 text-sage-600' : 'bg-white border-line text-ink-soft hover:border-sage-200'}`}>
                  <Icon size={14} />
                  {p.title}
                  <span className="text-[10.5px] text-ink-faint">{p.file_count} files</span>
                </button>
              );
            })}
          </div>
        )}

        {active && (
          <>
            <Card className="p-5 mb-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-[17px] font-extrabold tracking-[-0.02em] text-ink">{active.title}</div>
                  <p className="text-[13px] text-ink-muted mt-1 max-w-2xl leading-relaxed">{active.summary}</p>
                  <div className="flex flex-wrap items-center gap-1.5 mt-2.5">
                    <Badge tone="sage">{active.framework}</Badge>
                    <Badge tone="neutral">{active.file_count} files</Badge>
                    <Badge tone="neutral">{kb(active.total_bytes)}</Badge>
                    {active.topic_slug && (
                      <Link href={`/curriculum/view?slug=${active.topic_slug}`}>
                        <Badge tone="info">Open the lesson</Badge>
                      </Link>
                    )}
                  </div>
                </div>
                <a href={`/api/pipelines/${active.slug}/download`} download>
                  <Button size="sm" variant="outline" icon={<IcDownload size={13} />}>Download .zip</Button>
                </a>
              </div>

              {active.highlights?.length > 0 && (
                <ul className="mt-4 grid sm:grid-cols-2 gap-x-5 gap-y-1.5">
                  {active.highlights.map((h, i) => (
                    <li key={i} className="flex gap-2 text-[12.5px] text-ink-soft">
                      <span className="w-1 h-1 rounded-full bg-sage-500 mt-2 shrink-0" />
                      <span>{h}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <div className="grid lg:grid-cols-[260px_1fr] gap-4 items-start">
              <Card className="overflow-hidden">
                <div className="px-4 py-2.5 border-b border-line text-[10.5px] font-bold tracking-[0.16em] uppercase text-ink-muted">
                  Files
                </div>
                <div className="max-h-[560px] overflow-y-auto py-1">
                  {active.files?.map((f) => {
                    const on = f.path === path;
                    return (
                      <button key={f.path} onClick={() => view(active.slug, f.path)}
                        className={`w-full text-left px-4 py-1.5 flex items-center justify-between gap-2 transition-colors ${
                          on ? 'bg-sage-50' : 'hover:bg-paper-deep'}`}>
                        <span className={`text-[12px] mono truncate ${on ? 'text-sage-600 font-bold' : 'text-ink-soft'}`}>
                          {f.path}
                        </span>
                        <span className="text-[10px] text-ink-faint shrink-0 tabular-nums">{kb(f.size)}</span>
                      </button>
                    );
                  })}
                </div>
              </Card>

              <Card className="overflow-hidden">
                <div className="px-4 py-2.5 border-b border-line flex items-center gap-2">
                  <IcFileText size={13} className="text-ink-faint" />
                  <span className="text-[12px] mono font-bold text-ink">{path || '-'}</span>
                  {path === active.entrypoint && <Badge tone="sage">entrypoint</Badge>}
                </div>
                {!file && <Skeleton className="h-72" />}
                {file && (
                  <pre className="p-4 overflow-auto max-h-[560px] text-[12px] mono leading-relaxed bg-[#161A13] text-[#DCE5DA]">
                    <code>{file.content}</code>
                  </pre>
                )}
              </Card>
            </div>
          </>
        )}
      </Page>
      {node}
    </Shell>
  );
}
