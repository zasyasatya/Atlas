'use client';
import { useSearchParams } from 'next/navigation';
import React, { Suspense } from 'react';
import { api, auth, Deployment, fmtDate, Topic } from '@/lib/api';
import { Page, PageHeader, Shell } from '../components/Shell';
import {
  Badge, Button, Card, Empty, Field, Input, Modal, Progress, Select, Skeleton, StatusDot, useToast,
} from '../components/UI';
import {
  IcAlert, IcCheck, IcDownload, IcExternal, IcHelp, IcPlus, IcRefresh,
  IcRocket, IcTrash, IcUpload, IcX,
} from '../components/Icons';

export default function DeploymentPage() {
  return <Suspense fallback={null}><DeploymentView /></Suspense>;
}

function DeploymentView() {
  const params = useSearchParams();
  const { show, node } = useToast();
  const [topics, setTopics] = React.useState<Topic[]>([]);
  const [deps, setDeps] = React.useState<Deployment[] | null>(null);
  const [rubric, setRubric] = React.useState<any[]>([]);
  const [create, setCreate] = React.useState(false);
  const [busyId, setBusyId] = React.useState<number | null>(null);
  const canEdit = auth.canEdit();

  const load = React.useCallback(() => api.get<Deployment[]>('/api/deployments').then(setDeps).catch(() => setDeps([])), []);
  React.useEffect(() => {
    api.get<Topic[]>('/api/topics').then(setTopics).catch(() => {});
    api.get<any[]>('/api/deployments/rubric').then(setRubric).catch(() => {});
    load();
  }, [load]);

  async function act(id: number, path: string, msg: string) {
    setBusyId(id);
    try { await api.post(`/api/deployments/${id}/${path}`); await load(); show(msg); }
    catch (e: any) { show(e.message, 'bad'); } finally { setBusyId(null); }
  }

  async function remove(d: Deployment) {
    if (!confirm(`Delete "${d.name}"?`)) return;
    await api.del(`/api/deployments/${d.id}`); load(); show('Deleted');
  }

  return (
    <Shell>
      <PageHeader eyebrow="Deployment" title="Ship the web app"
        subtitle="Upload your Streamlit or Gradio app. ATLAS checks it against the five graduation requirements, generates a Dockerfile, and deploys it with one click."
        actions={<Button icon={<IcPlus size={15} />} onClick={() => setCreate(true)}>New deployment</Button>} />

      <Page className="space-y-5">
        <RubricCard rubric={rubric} />

        {!deps && <div className="space-y-3">{[0,1].map(i => <Skeleton key={i} className="h-48" />)}</div>}
        {deps && deps.length === 0 && (
          <Card>
            <Empty icon={<IcRocket size={20} />} title="No deployments yet"
              body="Create a deployment record, upload your app bundle (a .zip or a single app.py), and ATLAS grades it against the rubric before you deploy."
              action={<Button size="sm" icon={<IcPlus size={14} />} onClick={() => setCreate(true)}>New deployment</Button>} />
          </Card>
        )}

        {deps?.map((d) => (
          <DeploymentCard key={d.id} dep={d} topics={topics} busy={busyId === d.id}
            onAction={act} onReload={load} onDelete={canEdit ? remove : undefined} show={show} />
        ))}
      </Page>

      <CreateModal open={create} onClose={() => setCreate(false)} topics={topics}
        defaultTopic={params.get('topic') || ''}
        onDone={() => { setCreate(false); load(); show('Deployment created — upload your bundle next'); }} />
      {node}
    </Shell>
  );
}

function RubricCard({ rubric }: { rubric: any[] }) {
  const [open, setOpen] = React.useState(false);
  return (
    <Card className="overflow-hidden">
      <button onClick={() => setOpen(!open)} className="w-full flex items-center gap-3 px-5 py-4 hover:bg-paper-deep/30 transition-colors text-left">
        <div className="w-9 h-9 rounded-xl bg-sage-100 text-sage-700 grid place-items-center shrink-0">
          <IcHelp size={17} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[14px] font-bold text-ink">Graduation requirements</div>
          <div className="text-[12.5px] text-ink-muted">Five checks every internship web app must pass.</div>
        </div>
        <span className="text-[12px] font-bold text-sage-700">{open ? 'Hide' : 'Show'}</span>
      </button>
      {open && (
        <div className="px-5 pb-5 space-y-2 animate-rise">
          {rubric.map((r) => (
            <div key={r.id} className="flex gap-3 px-4 py-3 rounded-xl bg-paper-deep/60">
              <span className="text-[11px] font-extrabold text-sage-700 shrink-0 mt-0.5">{r.id}</span>
              <div>
                <div className="text-[13px] font-bold text-ink">{r.label}</div>
                <div className="text-[12px] text-ink-muted mt-0.5">{r.hint}</div>
              </div>
            </div>
          ))}
          <div className="flex gap-2 pt-2">
            <a href="/api/deployments/templates/streamlit" download>
              <Button size="sm" variant="outline" icon={<IcDownload size={13} />}>Streamlit starter</Button>
            </a>
            <a href="/api/deployments/templates/gradio" download>
              <Button size="sm" variant="outline" icon={<IcDownload size={13} />}>Gradio starter</Button>
            </a>
          </div>
        </div>
      )}
    </Card>
  );
}

function DeploymentCard({ dep, topics, busy, onAction, onReload, onDelete, show }: any) {
  const [uploading, setUploading] = React.useState(false);
  const [whim, setWhim] = React.useState(dep.whimsical_url || '');
  const [logs, setLogs] = React.useState(false);
  const fileRef = React.useRef<HTMLInputElement>(null);

  const passed = dep.checks.filter((c: any) => c.status === 'pass').length;
  const ready = dep.readiness_score >= 80;

  async function uploadBundle(file: File) {
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      await api.post(`/api/deployments/${dep.id}/bundle`, fd);
      await onReload();
      show('Bundle uploaded and checked');
    } catch (e: any) { show(e.message, 'bad'); } finally { setUploading(false); }
  }

  async function saveWhimsical() {
    const fd = new FormData();
    fd.append('whimsical_url', whim);
    await api.patch(`/api/deployments/${dep.id}`, fd);
    await onReload();
    show('Whimsical link saved');
  }

  return (
    <Card className="overflow-hidden">
      <div className="px-5 py-4 border-b border-line">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-[17px] font-extrabold tracking-[-0.02em] text-ink">{dep.name}</h3>
              <Badge tone={dep.framework === 'streamlit' ? 'info' : 'sage'}>{dep.framework}</Badge>
              <span className="flex items-center gap-1.5 text-[12px] font-semibold text-ink-muted capitalize">
                <StatusDot status={dep.status} /> {dep.status}
              </span>
            </div>
            <div className="text-[12.5px] text-ink-muted mt-1">
              {dep.topic_title} · {dep.owner_name} · {fmtDate(dep.created_at)} · entry <span className="mono">{dep.entrypoint}</span>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {dep.url && (
              <a href={dep.url} target="_blank" rel="noreferrer">
                <Button size="sm" variant="outline" icon={<IcExternal size={13} />}>Open app</Button>
              </a>
            )}
            {onDelete && (
              <button onClick={() => onDelete(dep)} className="p-2 rounded-lg text-ink-faint hover:bg-[#FAEBE8] hover:text-signal-bad">
                <IcTrash size={15} />
              </button>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3 mt-3.5">
          <Progress value={dep.readiness_score} tone={ready ? 'ok' : dep.readiness_score >= 50 ? 'warn' : 'bad'} />
          <span className={`text-[12px] font-extrabold tabular-nums shrink-0 ${ready ? 'text-signal-ok' : 'text-ink-muted'}`}>
            {dep.readiness_score}%
          </span>
          <Badge tone={ready ? 'ok' : 'neutral'}>{passed}/5 checks</Badge>
        </div>
      </div>

      <div className="grid md:grid-cols-2 divide-y md:divide-y-0 md:divide-x divide-line">
        {/* checks */}
        <div className="p-5">
          <div className="eyebrow mb-3">Rubric</div>
          <div className="space-y-1.5">
            {dep.checks.length === 0 && (
              <div className="text-[12.5px] text-ink-faint">Upload a bundle to run the checks.</div>
            )}
            {dep.checks.map((c: any) => (
              <div key={c.rule_id} className="flex gap-2.5">
                <span className={`w-4.5 h-4.5 rounded-md grid place-items-center shrink-0 mt-0.5 ${
                  c.status === 'pass' ? 'bg-signal-ok text-white' :
                  c.status === 'warn' ? 'bg-signal-warn text-white' : 'bg-signal-bad text-white'}`}
                  style={{ width: 18, height: 18 }}>
                  {c.status === 'pass' ? <IcCheck size={11} /> : c.status === 'warn' ? <IcAlert size={10} /> : <IcX size={11} />}
                </span>
                <div className="min-w-0">
                  <div className="text-[12.5px] font-bold text-ink leading-snug">
                    <span className="text-ink-faint mr-1">{c.rule_id}</span>{c.label}
                  </div>
                  {c.status !== 'pass' && (
                    <div className="text-[11.5px] text-ink-muted mt-0.5 leading-snug">{c.detail}</div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* actions */}
        <div className="p-5 space-y-3.5">
          <div className="eyebrow">Actions</div>

          <input ref={fileRef} type="file" className="hidden" accept=".zip,.py"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadBundle(f); }} />
          <Button variant="outline" className="w-full" loading={uploading}
            onClick={() => fileRef.current?.click()} icon={<IcUpload size={14} />}>
            {dep.checks.length ? 'Replace bundle' : 'Upload app bundle (.zip or app.py)'}
          </Button>

          <Field label="Whimsical board URL" hint="required by R5">
            <div className="flex gap-2">
              <Input value={whim} onChange={(e) => setWhim(e.target.value)} placeholder="https://whimsical.com/..." />
              <Button size="sm" variant="outline" onClick={saveWhimsical}>Save</Button>
            </div>
          </Field>

          <div className="grid grid-cols-2 gap-2">
            <Button variant="outline" size="sm" loading={busy}
              onClick={() => onAction(dep.id, 'check', 'Checks re-run')} icon={<IcRefresh size={13} />}>
              Re-check
            </Button>
            <a href={`/api/deployments/${dep.id}/dockerfile`} download>
              <Button variant="outline" size="sm" className="w-full" icon={<IcDownload size={13} />}>Dockerfile</Button>
            </a>
          </div>

          {dep.status === 'running' ? (
            <Button variant="outline" className="w-full" loading={busy}
              onClick={() => onAction(dep.id, 'stop', 'App stopped')}>Stop app</Button>
          ) : (
            <Button className="w-full" loading={busy}
              onClick={() => onAction(dep.id, 'deploy', 'Deployment triggered')} icon={<IcRocket size={15} />}>
              One-click deploy
            </Button>
          )}

          {dep.build_logs && (
            <button onClick={() => setLogs(!logs)} className="text-[11.5px] font-bold text-sage-700 hover:underline">
              {logs ? 'Hide' : 'Show'} build logs
            </button>
          )}
        </div>
      </div>

      {logs && dep.build_logs && (
        <pre className="bg-[#161A13] text-[#DCE5DA] p-4 text-[11.5px] mono leading-relaxed max-h-56 overflow-y-auto whitespace-pre-wrap">
          {dep.build_logs}
        </pre>
      )}
    </Card>
  );
}

function CreateModal({ open, onClose, topics, defaultTopic, onDone }: any) {
  const [name, setName] = React.useState('');
  const [topicId, setTopicId] = React.useState(defaultTopic || '');
  const [framework, setFramework] = React.useState('streamlit');
  const [entrypoint, setEntrypoint] = React.useState('app.py');
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => { if (defaultTopic) setTopicId(defaultTopic); }, [defaultTopic]);
  React.useEffect(() => { if (!topicId && topics[0]) setTopicId(String(topics[0].id)); }, [topics, topicId]);

  async function submit() {
    if (!name.trim()) return alert('Name is required');
    setBusy(true);
    try {
      await api.post('/api/deployments', {
        name, topic_id: Number(topicId), framework, entrypoint, whimsical_url: '',
      });
      setName('');
      onDone();
    } catch (e: any) { alert(e.message); } finally { setBusy(false); }
  }

  return (
    <Modal open={open} onClose={onClose} title="New deployment"
      subtitle="One record per web app. You can re-upload the bundle as many times as you like.">
      <div className="space-y-4">
        <Field label="App name" required>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Equipment Failure Predictor" />
        </Field>
        <Field label="Topic">
          <Select value={topicId} onChange={(e) => setTopicId(e.target.value)}>
            {topics.map((t: Topic) => <option key={t.id} value={t.id}>{t.title}</option>)}
          </Select>
        </Field>
        <Field label="Framework" hint="R1 allows these two only">
          <div className="grid grid-cols-2 gap-2">
            {['streamlit', 'gradio'].map((f) => (
              <button key={f} onClick={() => { setFramework(f); setEntrypoint('app.py'); }}
                className={`px-3.5 py-2.5 rounded-xl border text-left capitalize transition-all ${
                  framework === f ? 'bg-sage-50 border-sage-400' : 'bg-white border-line hover:border-sage-300'}`}>
                <div className="text-[13px] font-bold text-ink">{f}</div>
                <div className="text-[11px] text-ink-muted">
                  {f === 'streamlit' ? 'streamlit run app.py' : 'python app.py'}
                </div>
              </button>
            ))}
          </div>
        </Field>
        <Field label="Entrypoint" hint="auto-detected from your zip if missing">
          <Input value={entrypoint} onChange={(e) => setEntrypoint(e.target.value)} className="mono" />
        </Field>
        <div className="flex gap-2 pt-1">
          <Button onClick={submit} loading={busy} className="flex-1">Create</Button>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
        </div>
      </div>
    </Modal>
  );
}
