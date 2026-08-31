'use client';
import { useSearchParams } from 'next/navigation';
import React, { Suspense } from 'react';
import { api, Asset, fmtDate, Notebook, Run, Topic } from '@/lib/api';
import { Page, PageHeader, Shell } from '../components/Shell';
import { NotebookView } from '../components/Notebook';
import { Badge, Button, Card, Empty, Field, Modal, Select, Skeleton, StatusDot, Tabs, useToast } from '../components/UI';
import {
  IcAlert, IcCheck, IcCloud, IcCpu, IcDownload, IcExternal, IcFlask,
  IcGpu, IcPlay, IcRefresh, IcSpark,
} from '../components/Icons';

export default function PlaygroundPage() {
  return <Suspense fallback={null}><Playground /></Suspense>;
}

function Playground() {
  const params = useSearchParams();
  const { show, node } = useToast();
  const [topics, setTopics] = React.useState<Topic[]>([]);
  const [notebooks, setNotebooks] = React.useState<Notebook[]>([]);
  const [runs, setRuns] = React.useState<Run[]>([]);
  const [assets, setAssets] = React.useState<Asset[]>([]);
  const [targets, setTargets] = React.useState<any[]>([]);
  const [activeTopic, setActiveTopic] = React.useState<number | null>(null);
  const [activeNb, setActiveNb] = React.useState<Notebook | null>(null);
  const [nbDoc, setNbDoc] = React.useState<any>(null);
  const [launching, setLaunching] = React.useState(false);
  const [launchModal, setLaunchModal] = React.useState<any>(null);
  const [tab, setTab] = React.useState('notebook');

  const loadRuns = React.useCallback(() => api.get<Run[]>('/api/runs').then(setRuns).catch(() => {}), []);

  React.useEffect(() => {
    Promise.all([
      api.get<Topic[]>('/api/topics'),
      api.get<Notebook[]>('/api/notebooks'),
      api.get<Asset[]>('/api/assets?kind=dataset'),
      api.get<any[]>('/api/compute/targets'),
    ]).then(([t, n, a, c]) => {
      setTopics(t); setNotebooks(n); setAssets(a); setTargets(c);
      const q = params.get('topic');
      const initial = q ? Number(q) : t[0]?.id ?? null;
      setActiveTopic(initial);
      const nb = n.find((x) => x.topic_id === initial) || n[0] || null;
      setActiveNb(nb);
    }).catch(() => {});
    loadRuns();
  }, [params, loadRuns]);

  React.useEffect(() => {
    if (!activeNb) return setNbDoc(null);
    api.get<any>(`/api/notebooks/${activeNb.id}`).then((d) => setNbDoc(d.content)).catch(() => {});
  }, [activeNb]);

  // poll while anything is in flight
  React.useEffect(() => {
    const live = runs.some((r) => ['running', 'queued', 'pending'].includes(r.status));
    if (!live) return;
    const t = setInterval(loadRuns, 4000);
    return () => clearInterval(t);
  }, [runs, loadRuns]);

  const topicNbs = notebooks.filter((n) => n.topic_id === activeTopic);
  const topicRuns = runs.filter((r) => r.topic_id === activeTopic);
  const topicAssets = assets.filter((a) => a.topic_id === activeTopic);
  const topic = topics.find((t) => t.id === activeTopic);

  async function launch(target: string, datasetId: number | null) {
    if (!activeNb) return;
    setLaunching(true);
    try {
      const res = await api.post<any>('/api/runs', {
        notebook_id: activeNb.id, target, dataset_asset_id: datasetId,
      });
      setLaunchModal(res);
      loadRuns();
      if (res.upgraded) show(`GPU required — routed to ${res.run.target.replace('_', ' ')}`, 'warn');
      else show('Run dispatched');
    } catch (e: any) { show(e.message, 'bad'); } finally { setLaunching(false); }
  }

  return (
    <Shell>
      <PageHeader eyebrow="Playground" title="Notebooks & compute"
        subtitle="Run a guided notebook per topic. Heavy vision training is routed to a borrowed GPU automatically — no GPU on this server, and none needed."
        actions={<Button variant="outline" icon={<IcRefresh size={15} />} onClick={loadRuns}>Refresh</Button>} />

      <Page>
        {/* topic selector */}
        <div className="flex gap-2 overflow-x-auto pb-3 mb-5 -mx-1 px-1">
          {topics.map((t) => (
            <button key={t.id} onClick={() => { setActiveTopic(t.id); setActiveNb(notebooks.find((n) => n.topic_id === t.id) || null); }}
              className={`px-3.5 py-2 rounded-xl text-[13px] font-bold whitespace-nowrap border transition-all ${
                activeTopic === t.id ? 'bg-ink text-white border-ink' : 'bg-white text-ink-soft border-line hover:border-sage-300'}`}>
              {t.title}
              {t.heavy_compute && <span className="ml-1.5 opacity-70">GPU</span>}
            </button>
          ))}
        </div>

        <div className="grid lg:grid-cols-[1fr,330px] gap-5">
          {/* notebook */}
          <div className="space-y-4">
            {topicNbs.length > 1 && (
              <div className="flex flex-wrap gap-2">
                {topicNbs.map((n) => (
                  <button key={n.id} onClick={() => setActiveNb(n)}
                    title={n.description}
                    className={`px-3 py-1.5 rounded-lg text-[12.5px] font-semibold border ${
                      activeNb?.id === n.id ? 'bg-sage-100 border-sage-300 text-sage-800' : 'bg-white border-line text-ink-muted'}`}>
                    {n.title}
                    {n.requires_gpu && <span className="ml-1.5 opacity-60">GPU</span>}
                  </button>
                ))}
              </div>
            )}

            {!activeNb ? (
              <Card><Empty icon={<IcFlask size={20} />} title="No notebook for this topic"
                body="A supervisor can attach a playground notebook to this topic." /></Card>
            ) : (
              <Card className="overflow-hidden">
                <div className="px-5 py-4 border-b border-line">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h2 className="text-[16px] font-extrabold tracking-[-0.02em] text-ink">{activeNb.title}</h2>
                      <p className="text-[12.5px] text-ink-muted mt-0.5">{activeNb.description}</p>
                    </div>
                    <div className="flex gap-1.5 shrink-0">
                      {activeNb.requires_gpu && <Badge tone="warn"><IcGpu size={10} /> GPU required</Badge>}
                      <Badge tone="neutral">v{activeNb.version}</Badge>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 mt-3">
                    <a href={`/api/notebooks/${activeNb.id}/export.ipynb`} download>
                      <Button size="sm" variant="outline" icon={<IcDownload size={13} />}>Download .ipynb</Button>
                    </a>
                    <span className="text-[11.5px] text-ink-faint">{activeNb.cell_count} cells · updated {fmtDate(activeNb.updated_at)}</span>
                  </div>
                </div>

                <Tabs active={tab} onChange={setTab}
                  tabs={[{ id: 'notebook', label: 'Notebook' }, { id: 'runs', label: 'Runs', count: topicRuns.length }]} />

                {tab === 'notebook' ? (
                  <div className="p-4 max-h-[620px] overflow-y-auto bg-paper-deep">
                    {!nbDoc && <Skeleton className="h-40" />}
                    {nbDoc && <NotebookView doc={nbDoc} />}
                  </div>
                ) : (
                  <div className="divide-y divide-line max-h-[620px] overflow-y-auto">
                    {topicRuns.length === 0 && (
                      <Empty icon={<IcPlay size={20} />} title="No runs for this topic yet"
                        body="Pick a compute target on the right and launch the notebook." />
                    )}
                    {topicRuns.map((r) => <RunRow key={r.id} run={r} />)}
                  </div>
                )}
              </Card>
            )}
          </div>

          {/* launcher */}
          <div className="space-y-4">
            <Launcher targets={targets} assets={topicAssets} notebook={activeNb} topic={topic}
              onLaunch={launch} busy={launching} />

            <Card className="p-4">
              <div className="eyebrow mb-2.5">How the GPU bridge works</div>
              <ol className="space-y-2 text-[12.5px] text-ink-soft leading-relaxed list-none">
                {[
                  'ATLAS injects a bridge cell into your notebook.',
                  'The notebook opens on Colab or is pushed headless to Kaggle.',
                  'Your code calls atlas.metric(...) and atlas.artifact(...).',
                  'Logs, metrics and model files stream back into this page.',
                ].map((s, i) => (
                  <li key={i} className="flex gap-2.5">
                    <span className="w-4.5 h-4.5 rounded-md bg-sage-100 text-sage-800 text-[10px] font-bold grid place-items-center shrink-0 mt-0.5" style={{ width: 18, height: 18 }}>{i + 1}</span>
                    <span>{s}</span>
                  </li>
                ))}
              </ol>
            </Card>
          </div>
        </div>
      </Page>

      <Modal open={!!launchModal} onClose={() => setLaunchModal(null)} title="Run dispatched"
        subtitle={launchModal?.upgraded ? 'This notebook needs a GPU, so ATLAS upgraded the target.' : undefined}>
        {launchModal && (
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <StatusDot status={launchModal.run.status} />
              <span className="text-[13.5px] font-bold capitalize">{launchModal.run.status}</span>
              <Badge tone="info">{launchModal.run.target.replace('_', ' ')}</Badge>
            </div>
            {launchModal.instructions?.length > 0 && (
              <ol className="space-y-1.5">
                {launchModal.instructions.map((s: string, i: number) => (
                  <li key={i} className="flex gap-2.5 text-[13px] text-ink-soft">
                    <span className="text-sage-600 font-bold">{i + 1}.</span>
                    <span className="break-all">{s}</span>
                  </li>
                ))}
              </ol>
            )}
            {launchModal.run.external_url && (
              <a href={launchModal.run.external_url} target="_blank" rel="noreferrer">
                <Button className="w-full" icon={<IcExternal size={15} />}>
                  Open {launchModal.run.target === 'kaggle_gpu' ? 'Kaggle kernel' : 'in Colab'}
                </Button>
              </a>
            )}
          </div>
        )}
      </Modal>
      {node}
    </Shell>
  );
}

function Launcher({ targets, assets, notebook, topic, onLaunch, busy }: any) {
  const [target, setTarget] = React.useState('local_cpu');
  const [dataset, setDataset] = React.useState<string>('');

  React.useEffect(() => {
    if (notebook?.requires_gpu) setTarget(notebook.default_target || 'colab_gpu');
    else setTarget('local_cpu');
  }, [notebook]);

  const chosen = targets.find((t: any) => t.id === target);
  const mismatch = notebook?.requires_gpu && target === 'local_cpu';

  return (
    <Card className="p-4">
      <div className="eyebrow mb-3">Launch run</div>
      <div className="space-y-3">
        <Field label="Compute target">
          <div className="space-y-1.5">
            {targets.map((t: any) => (
              <button key={t.id} onClick={() => setTarget(t.id)} disabled={!t.available}
                className={`w-full text-left px-3 py-2.5 rounded-xl border transition-all disabled:opacity-45 ${
                  target === t.id ? 'bg-sage-50 border-sage-400' : 'bg-white border-line hover:border-sage-300'}`}>
                <div className="flex items-center gap-2">
                  {t.gpu ? <IcGpu size={14} className="text-sage-600" /> : <IcCpu size={14} className="text-ink-faint" />}
                  <span className="text-[13px] font-bold text-ink flex-1">{t.label}</span>
                  {t.gpu && <Badge tone="sage">GPU</Badge>}
                  {!t.available && <Badge tone="neutral">setup</Badge>}
                </div>
                <div className="text-[11.5px] text-ink-muted mt-1 leading-snug">{t.detail}</div>
              </button>
            ))}
          </div>
        </Field>

        {mismatch && (
          <div className="flex gap-2 px-3 py-2.5 rounded-xl bg-[#FBF3E2] border border-[#EEDFBE]">
            <IcAlert size={14} className="text-[#8A6420] shrink-0 mt-0.5" />
            <span className="text-[12px] text-[#8A6420] leading-snug">
              This notebook needs a GPU. ATLAS will reroute the run to {notebook.default_target?.replace('_', ' ')}.
            </span>
          </div>
        )}

        <Field label="Attach dataset" hint="optional">
          <Select value={dataset} onChange={(e) => setDataset(e.target.value)}>
            <option value="">None — notebook uses sample data</option>
            {assets.map((a: Asset) => (
              <option key={a.id} value={a.id}>{a.title} (v{a.version})</option>
            ))}
          </Select>
        </Field>

        <Button className="w-full" loading={busy} disabled={!notebook}
          onClick={() => onLaunch(target, dataset ? Number(dataset) : null)}
          icon={<IcPlay size={14} />}>
          Run notebook
        </Button>

        {chosen && !chosen.available && (
          <p className="text-[11.5px] text-ink-faint leading-snug">
            {chosen.label} needs credentials in the platform environment. See Settings.
          </p>
        )}
      </div>
    </Card>
  );
}

function RunRow({ run }: { run: Run }) {
  const [open, setOpen] = React.useState(false);
  const metrics = Object.entries(run.metrics || {});
  return (
    <div>
      <button onClick={() => setOpen(!open)} className="w-full flex items-center gap-3 px-5 py-3 hover:bg-paper-deep/40 transition-colors text-left">
        <StatusDot status={run.status} />
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-semibold text-ink">Run #{run.id} · <span className="capitalize">{run.status}</span></div>
          <div className="text-[11.5px] text-ink-muted">
            {run.user_name} · {fmtDate(run.created_at)}{run.duration_seconds > 0 && ` · ${run.duration_seconds}s`}
          </div>
        </div>
        {metrics.slice(0, 2).map(([k, v]) => (
          <Badge key={k} tone="sage">{k.replace(/_/g, ' ')} {typeof v === 'number' ? (v as number).toFixed(3) : String(v)}</Badge>
        ))}
        <Badge tone={run.target === 'local_cpu' ? 'neutral' : 'info'}>
          {run.target === 'local_cpu' ? <IcCpu size={10} /> : <IcGpu size={10} />} {run.target.replace('_', ' ')}
        </Badge>
      </button>
      {open && (
        <div className="px-5 pb-4 space-y-3 animate-rise">
          {run.external_url && (
            <a href={run.external_url} target="_blank" rel="noreferrer">
              <Button size="sm" variant="outline" icon={<IcExternal size={13} />}>Open remote runtime</Button>
            </a>
          )}
          {metrics.length > 0 && (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {metrics.map(([k, v]) => (
                <div key={k} className="px-3 py-2 rounded-xl bg-paper-deep">
                  <div className="text-[10.5px] text-ink-muted font-semibold uppercase tracking-wide">{k.replace(/_/g, ' ')}</div>
                  <div className="text-[15px] font-extrabold text-ink tabular-nums">
                    {typeof v === 'number' ? (v as number).toFixed(4).replace(/0+$/, '').replace(/\.$/, '') : String(v)}
                  </div>
                </div>
              ))}
            </div>
          )}
          {run.error && (
            <div className="px-3 py-2.5 rounded-xl bg-[#FAEBE8] border border-[#EED2CB]">
              <div className="text-[11.5px] font-bold text-[#8F3B2C] mb-1">Error</div>
              <pre className="text-[11.5px] text-[#8F3B2C] whitespace-pre-wrap mono leading-relaxed max-h-32 overflow-y-auto">{run.error}</pre>
            </div>
          )}
          {run.logs && (
            <div className="rounded-xl overflow-hidden border border-line">
              <div className="px-3 py-1.5 bg-ink text-white text-[10.5px] font-semibold">LOGS</div>
              <pre className="bg-[#161A13] text-[#DCE5DA] p-3 text-[11.5px] mono leading-relaxed max-h-56 overflow-y-auto whitespace-pre-wrap">{run.logs.trim()}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
