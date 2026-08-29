'use client';
import { useSearchParams } from 'next/navigation';
import React, { Suspense } from 'react';
import { api, Asset, auth, fmtBytes, fmtDate, Topic } from '@/lib/api';
import { Page, PageHeader, Shell } from '../components/Shell';
import { Badge, Button, Card, Empty, Field, Input, Modal, Select, Skeleton, Tabs, Textarea, useToast } from '../components/UI';
import {
  IcDatabase, IcDownload, IcPlus, IcSlides, IcTrash, IcUpload,
} from '../components/Icons';

const STAGES = [
  { id: 'raw', label: 'Raw' },
  { id: 'cleaned', label: 'Cleaned' },
  { id: 'features', label: 'Features' },
  { id: 'split', label: 'Train/test split' },
  { id: 'model', label: 'Model artifact' },
];

export default function DatasetsPage() {
  return <Suspense fallback={null}><Datasets /></Suspense>;
}

function Datasets() {
  const params = useSearchParams();
  const { show, node } = useToast();
  const [tab, setTab] = React.useState(params.get('tab') === 'decks' ? 'deck' : 'dataset');
  const [topics, setTopics] = React.useState<Topic[]>([]);
  const [assets, setAssets] = React.useState<Asset[] | null>(null);
  const [filter, setFilter] = React.useState<string>(params.get('topic') || '');
  const [upload, setUpload] = React.useState(false);
  const [detail, setDetail] = React.useState<Asset | null>(null);
  const canEdit = auth.canEdit();

  const load = React.useCallback(() => api.get<Asset[]>('/api/assets').then(setAssets).catch(() => setAssets([])), []);
  React.useEffect(() => { api.get<Topic[]>('/api/topics').then(setTopics).catch(() => {}); load(); }, [load]);

  const rows = (assets || []).filter((a) =>
    (tab === 'deck' ? a.kind === 'deck' : a.kind === 'dataset' || a.kind === 'artifact') &&
    (!filter || String(a.topic_id) === filter));

  async function remove(a: Asset) {
    if (!confirm(`Delete "${a.title}"?`)) return;
    await api.del(`/api/assets/${a.id}`);
    load(); show('Deleted');
  }

  return (
    <Shell>
      <PageHeader eyebrow="Library" title="Datasets & decks"
        subtitle="Every upload is versioned and attributed. Attach a dataset to a notebook run and the remote GPU downloads it automatically."
        actions={<Button icon={<IcUpload size={15} />} onClick={() => setUpload(true)}>Upload</Button>} />

      <Page className="space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Tabs active={tab} onChange={setTab} tabs={[
            { id: 'dataset', label: 'Datasets & artifacts', count: (assets || []).filter(a => a.kind !== 'deck').length },
            { id: 'deck', label: 'Preparation decks', count: (assets || []).filter(a => a.kind === 'deck').length },
          ]} />
          <Select value={filter} onChange={(e) => setFilter(e.target.value)} className="w-auto min-w-[190px]">
            <option value="">All topics</option>
            {topics.map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
          </Select>
        </div>

        {!assets && <div className="space-y-3">{[0,1,2].map(i => <Skeleton key={i} className="h-20" />)}</div>}

        {assets && rows.length === 0 && (
          <Card>
            <Empty icon={tab === 'deck' ? <IcSlides size={20} /> : <IcDatabase size={20} />}
              title={tab === 'deck' ? 'No decks yet' : 'No datasets yet'}
              body={tab === 'deck'
                ? 'Upload the PPT that explains each dataset-preparation step. Slide titles are extracted automatically so interns can skim before opening the file.'
                : 'Upload CSV, XLSX or a zipped image set. Columns and row counts are detected on upload.'}
              action={<Button size="sm" icon={<IcUpload size={14} />} onClick={() => setUpload(true)}>Upload {tab === 'deck' ? 'deck' : 'dataset'}</Button>} />
          </Card>
        )}

        <div className="space-y-2.5">
          {rows.map((a) => {
            const topic = topics.find((t) => t.id === a.topic_id);
            return (
              <Card key={a.id} hover className="p-4">
                <div className="flex items-start gap-3.5">
                  <div className="w-10 h-10 rounded-xl bg-paper-deep grid place-items-center shrink-0 text-ink-muted">
                    {a.kind === 'deck' ? <IcSlides size={17} /> : <IcDatabase size={17} />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <button onClick={() => setDetail(a)} className="text-[14px] font-bold text-ink hover:text-sage-700 truncate">
                        {a.title}
                      </button>
                      <Badge tone="neutral">v{a.version}</Badge>
                      {a.kind === 'artifact' && <Badge tone="sage">artifact</Badge>}
                      <Badge tone="info">{STAGES.find(s => s.id === a.stage)?.label || a.stage}</Badge>
                    </div>
                    {a.description && <p className="text-[12.5px] text-ink-muted mt-1 line-clamp-1">{a.description}</p>}
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-ink-faint mt-1.5">
                      <span>{a.filename}</span>
                      <span>{fmtBytes(a.size_bytes)}</span>
                      {a.row_count != null && <span>{a.row_count.toLocaleString()} rows × {a.column_count} cols</span>}
                      {a.slide_count != null && <span>{a.slide_count} slides</span>}
                      {topic && <span className="text-sage-700 font-semibold">{topic.title}</span>}
                      <span>{a.uploader_name} · {fmtDate(a.created_at)}</span>
                    </div>
                  </div>
                  <div className="flex gap-1 shrink-0">
                    <a href={`/api/assets/${a.id}/download`} download>
                      <button className="p-2 rounded-lg text-ink-faint hover:bg-paper-deep hover:text-ink"><IcDownload size={15} /></button>
                    </a>
                    {canEdit && (
                      <button onClick={() => remove(a)} className="p-2 rounded-lg text-ink-faint hover:bg-[#FAEBE8] hover:text-signal-bad"><IcTrash size={15} /></button>
                    )}
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      </Page>

      <UploadModal open={upload} onClose={() => setUpload(false)} topics={topics} defaultKind={tab}
        onDone={() => { setUpload(false); load(); show('Upload complete'); }} />
      <DetailModal asset={detail} onClose={() => setDetail(null)} />
      {node}
    </Shell>
  );
}

function UploadModal({ open, onClose, topics, defaultKind, onDone }: any) {
  const [file, setFile] = React.useState<File | null>(null);
  const [kind, setKind] = React.useState(defaultKind === 'deck' ? 'deck' : 'dataset');
  const [topicId, setTopicId] = React.useState('');
  const [title, setTitle] = React.useState('');
  const [description, setDescription] = React.useState('');
  const [stage, setStage] = React.useState('raw');
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => { setKind(defaultKind === 'deck' ? 'deck' : 'dataset'); }, [defaultKind, open]);

  async function submit() {
    if (!file) return alert('Choose a file');
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('kind', kind);
      fd.append('stage', stage);
      if (topicId) fd.append('topic_id', topicId);
      if (title) fd.append('title', title);
      if (description) fd.append('description', description);
      await api.post('/api/assets', fd);
      setFile(null); setTitle(''); setDescription('');
      onDone();
    } catch (e: any) { alert(e.message); } finally { setBusy(false); }
  }

  return (
    <Modal open={open} onClose={onClose} title="Upload to the library"
      subtitle="Datasets feed notebook runs. Decks document how each dataset was prepared.">
      <div className="space-y-4">
        <Field label="Type">
          <div className="grid grid-cols-2 gap-2">
            {[{ id: 'dataset', label: 'Dataset', hint: 'CSV, XLSX, ZIP' },
              { id: 'deck', label: 'Preparation deck', hint: 'PPTX, PDF' }].map((k) => (
              <button key={k.id} onClick={() => setKind(k.id)}
                className={`px-3.5 py-2.5 rounded-xl border text-left transition-all ${
                  kind === k.id ? 'bg-sage-50 border-sage-400' : 'bg-white border-line hover:border-sage-300'}`}>
                <div className="text-[13px] font-bold text-ink">{k.label}</div>
                <div className="text-[11px] text-ink-muted">{k.hint}</div>
              </button>
            ))}
          </div>
        </Field>

        <Field label="File" required>
          <label className="flex flex-col items-center justify-center gap-2 px-4 py-7 border border-dashed border-line-strong rounded-2xl cursor-pointer hover:border-sage-400 hover:bg-sage-50/50 transition-all">
            <IcUpload size={20} className="text-ink-faint" />
            <span className="text-[13px] font-semibold text-ink-soft">
              {file ? file.name : 'Choose a file'}
            </span>
            {file && <span className="text-[11.5px] text-ink-faint">{fmtBytes(file.size)}</span>}
            <input type="file" className="hidden" onChange={(e) => setFile(e.target.files?.[0] || null)}
              accept={kind === 'deck' ? '.pptx,.pdf,.ppt' : '.csv,.xlsx,.xls,.zip,.json,.txt'} />
          </label>
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Topic">
            <Select value={topicId} onChange={(e) => setTopicId(e.target.value)}>
              <option value="">Unassigned</option>
              {topics.map((t: Topic) => <option key={t.id} value={t.id}>{t.title}</option>)}
            </Select>
          </Field>
          <Field label="Pipeline stage">
            <Select value={stage} onChange={(e) => setStage(e.target.value)}>
              {STAGES.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </Select>
          </Field>
        </div>

        <Field label="Title" hint="defaults to the filename">
          <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. P&ID annotated set — batch 3" />
        </Field>
        <Field label="Notes">
          <Textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)}
            placeholder="What changed in this version? Any caveats?" />
        </Field>

        <div className="flex gap-2 pt-1">
          <Button onClick={submit} loading={busy} className="flex-1" icon={<IcUpload size={15} />}>Upload</Button>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
        </div>
      </div>
    </Modal>
  );
}

function DetailModal({ asset, onClose }: { asset: Asset | null; onClose: () => void }) {
  if (!asset) return null;
  const p = asset.preview || {};
  return (
    <Modal open onClose={onClose} wide title={asset.title} subtitle={`${asset.filename} · v${asset.version} · ${fmtBytes(asset.size_bytes)}`}>
      <div className="space-y-4 max-h-[64vh] overflow-y-auto">
        {asset.description && <p className="text-[13.5px] text-ink-soft">{asset.description}</p>}

        {p.columns && (
          <div>
            <div className="eyebrow mb-2">Schema — {p.column_count} columns, {(p.row_count || 0).toLocaleString()} rows</div>
            <div className="border border-line rounded-xl overflow-hidden overflow-x-auto">
              <table className="w-full text-[12px]">
                <thead className="bg-paper-deep">
                  <tr>{p.columns.map((c: string, i: number) => (
                    <th key={i} className="px-3 py-2 text-left font-bold text-ink whitespace-nowrap">{c}</th>))}</tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {(p.rows_preview || []).map((row: any[], i: number) => (
                    <tr key={i} className="hover:bg-paper-deep/40">
                      {row.map((cell, j) => (
                        <td key={j} className="px-3 py-1.5 text-ink-soft whitespace-nowrap mono">{String(cell).slice(0, 40)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {p.slides && (
          <div>
            <div className="eyebrow mb-2">Slides — {p.slide_count}</div>
            <div className="space-y-1.5">
              {p.slides.map((s: any) => (
                <div key={s.index} className="flex gap-3 px-3.5 py-2.5 rounded-xl border border-line">
                  <span className="text-[11px] font-bold text-ink-faint shrink-0 mt-0.5">{String(s.index).padStart(2, '0')}</span>
                  <div className="min-w-0">
                    <div className="text-[13px] font-bold text-ink">{s.title}</div>
                    {s.bullets?.length > 0 && (
                      <ul className="mt-1 space-y-0.5">
                        {s.bullets.map((b: string, i: number) => (
                          <li key={i} className="text-[12px] text-ink-muted line-clamp-1">· {b}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {!p.columns && !p.slides && (
          <div className="text-[13px] text-ink-faint py-6 text-center">
            No structured preview for this file type. Download it to inspect.
          </div>
        )}

        <a href={`/api/assets/${asset.id}/download`} download>
          <Button className="w-full" variant="outline" icon={<IcDownload size={15} />}>Download original</Button>
        </a>
      </div>
    </Modal>
  );
}
