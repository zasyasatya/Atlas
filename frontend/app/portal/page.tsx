'use client';
import React from 'react';
import { api, auth, Deployment, fmtDate, Topic } from '@/lib/api';
import { Page, PageHeader, Shell } from '../components/Shell';
import { Badge, Button, Card, Empty, Modal, Progress, Select, Skeleton, StatusDot, useToast } from '../components/UI';
import { IcAlert, IcApps, IcCheck, IcDownload, IcExternal, IcTrophy } from '../components/Icons';

export default function Portal() {
  const [deps, setDeps] = React.useState<Deployment[] | null>(null);
  const [topics, setTopics] = React.useState<Topic[]>([]);
  const [filter, setFilter] = React.useState('');
  const [proxy, setProxy] = React.useState<string | null>(null);
  const [proxyStat, setProxyStat] = React.useState<any | null>(null);
  const [proxyOpen, setProxyOpen] = React.useState(false);
  const { show, node } = useToast();
  const canEdit = auth.canEdit();

  const loadProxy = async () => {
    setProxyOpen(true);
    setProxy(null);
    try {
      const [cfg, stat] = await Promise.all([
        api.get<string>('/api/deployments/proxy-config'),
        api.get<any>('/api/deployments/proxy-status').catch(() => null),
      ]);
      setProxy(cfg);
      setProxyStat(stat);
    } catch (e: any) {
      show(e.message || 'Could not load proxy config', 'bad');
      setProxyOpen(false);
    }
  };

  React.useEffect(() => {
    api.get<Deployment[]>('/api/deployments').then(setDeps).catch(() => setDeps([]));
    api.get<Topic[]>('/api/topics').then(setTopics).catch(() => {});
  }, []);

  const rows = (deps || []).filter((d) => !filter || String(d.topic_id) === filter);
  const live = rows.filter((d) => d.status === 'running');
  const graduated = rows.filter((d) => d.readiness_score >= 80);

  return (
    <Shell>
      <PageHeader eyebrow="Portal" title="App portal"
        subtitle="Every app the cohort has shipped, with its rubric score and live URL. This is the documentation surface supervisors review."
        actions={
          <div className="flex items-center gap-2">
            {canEdit && (
              <Button variant="outline" icon={<IcDownload size={14} />} onClick={loadProxy}>Proxy config</Button>
            )}
            <Select value={filter} onChange={(e) => setFilter(e.target.value)} className="w-auto min-w-[180px]">
              <option value="">All topics</option>
              {topics.map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
            </Select>
          </div>
        } />

      <Page className="space-y-5">
        <div className="grid grid-cols-3 gap-3.5">
          {[['Total apps', rows.length], ['Live now', live.length], ['Graduation ready', graduated.length]].map(([l, v]) => (
            <Card key={l as string} className="p-4">
              <div className="text-[11.5px] font-semibold text-ink-muted mb-1.5">{l}</div>
              <div className="text-[28px] font-extrabold tracking-[-0.04em] leading-none text-ink tabular-nums">{v as number}</div>
            </Card>
          ))}
        </div>

        {!deps && <div className="grid md:grid-cols-2 gap-4">{[0,1].map(i => <Skeleton key={i} className="h-40" />)}</div>}
        {deps && rows.length === 0 && (
          <Card><Empty icon={<IcApps size={20} />} title="No apps published yet"
            body="Apps appear here automatically the moment an intern deploys from the Deployment page." /></Card>
        )}

        <div className="grid md:grid-cols-2 gap-4">
          {rows.map((d) => (
            <Card key={d.id} hover className="p-5 flex flex-col">
              <div className="flex items-start justify-between gap-3 mb-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <Badge tone={d.framework === 'streamlit' ? 'info' : 'sage'}>{d.framework}</Badge>
                    {d.readiness_score >= 80 && <Badge tone="ok"><IcTrophy size={10} /> ready</Badge>}
                  </div>
                  <h3 className="text-[16px] font-extrabold tracking-[-0.02em] text-ink leading-tight">{d.name}</h3>
                  <div className="text-[12.5px] text-ink-muted mt-0.5">{d.topic_title} · {d.owner_name}</div>
                </div>
                <span className="flex items-center gap-1.5 text-[11.5px] font-semibold text-ink-muted capitalize shrink-0">
                  <StatusDot status={d.status} />{d.status}
                </span>
              </div>

              <div className="flex items-center gap-2.5 mb-3.5">
                <Progress value={d.readiness_score} tone={d.readiness_score >= 80 ? 'ok' : d.readiness_score >= 50 ? 'warn' : 'bad'} height={5} />
                <span className="text-[11.5px] font-bold tabular-nums text-ink-muted shrink-0">{d.readiness_score}%</span>
              </div>

              <div className="flex flex-wrap gap-1 mb-4">
                {d.checks.map((c) => (
                  <span key={c.rule_id} title={`${c.label}: ${c.detail}`}
                    className={`text-[10px] font-extrabold px-1.5 py-0.5 rounded ${
                      c.status === 'pass' ? 'bg-[#EAF3EC] text-[#33663F]' :
                      c.status === 'warn' ? 'bg-[#FBF3E2] text-[#8A6420]' : 'bg-[#FAEBE8] text-[#8F3B2C]'}`}>
                    {c.rule_id}
                  </span>
                ))}
              </div>

              <div className="mt-auto flex gap-2">
                {d.url ? (
                  <a href={d.url} target="_blank" rel="noreferrer" className="flex-1">
                    <Button size="sm" className="w-full" icon={<IcExternal size={13} />}>Open app</Button>
                  </a>
                ) : (
                  <Button size="sm" variant="outline" className="flex-1" disabled>Not deployed</Button>
                )}
                {d.whimsical_url && (
                  <a href={d.whimsical_url} target="_blank" rel="noreferrer">
                    <Button size="sm" variant="outline" icon={<IcExternal size={13} />}>Whimsical</Button>
                  </a>
                )}
              </div>
            </Card>
          ))}
        </div>
      </Page>

      <Modal open={proxyOpen} onClose={() => setProxyOpen(false)} title="Reverse proxy (nginx)"
        subtitle="Every app is served automatically as a virtual directory under /app/<slug> on the main domain — no per-app ports. nginx is regenerated and reloaded on each deploy/stop; this config is for first-time setup or review." wide>
        {proxy === null ? (
          <div className="text-[13px] text-ink-soft py-6 text-center">Loading…</div>
        ) : (
          <div className="space-y-3">
            {proxyStat && (
              <div className={`flex items-start gap-3 rounded-xl px-4 py-3 text-[12.5px] leading-snug ${
                proxyStat.nginx_present ? 'bg-[#EAF3EC] text-[#33663F]' : 'bg-[#FBF3E2] text-[#8A6420]'}`}>
                <span className="mt-0.5 shrink-0">{proxyStat.nginx_present ? <IcCheck size={15} /> : <IcAlert size={15} />}</span>
                <div>
                  {proxyStat.nginx_present ? (
                    <>
                      <b>Automatic nginx sync is active.</b> ATLAS writes one managed snippet per app and
                      reloads nginx safely (validated first, rolled back on error) — other sites are untouched.
                      <div className="text-[11.5px] opacity-80 mt-0.5">
                        {proxyStat.managed_snippets} managed app block(s) in <span className="mono">{proxyStat.conf_dir}</span>
                      </div>
                    </>
                  ) : (
                    <>
                      <b>nginx not detected on this host.</b> Config is generated automatically on every deploy
                      and stored ready to install. Copy <span className="mono">atlas.conf</span> into nginx once
                      (instructions at the top of the file), then set <span className="mono">ATLAS_NGINX_CONF_DIR</span> and
                      <span className="mono"> ATLAS_NGINX_RELOAD_CMD</span> to make reloads fully automatic.
                    </>
                  )}
                </div>
              </div>
            )}
            <div className="max-h-[50vh] overflow-auto rounded-xl bg-ink text-[#DDE7DF] p-4 text-[12px] mono whitespace-pre leading-relaxed">
              {proxy}
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setProxyOpen(false)}>Close</Button>
              <Button icon={<IcDownload size={14} />}
                onClick={() => {
                  const blob = new Blob([proxy], { type: 'text/plain' });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url; a.download = 'atlas.conf'; a.click();
                  URL.revokeObjectURL(url);
                }}>
                Download
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </Shell>
  );
}
