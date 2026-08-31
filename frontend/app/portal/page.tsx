'use client';
import React from 'react';
import { api, appHref, auth, Deployment, RoutingStatus, Topic } from '@/lib/api';
import { useBrand, getAppPrefix } from '@/lib/brand';
import { Page, PageHeader, Shell } from '../components/Shell';
import { Badge, Button, Card, Empty, Modal, Progress, Select, Skeleton, StatusDot, useToast } from '../components/UI';
import { IcAlert, IcApps, IcCheck, IcDownload, IcExternal, IcRefresh, IcTrophy } from '../components/Icons';

/**
 * The public surface for deployed apps.
 *
 * Two things are deliberately kept apart here, because users conflate them and
 * then debug the wrong one: whether a path is *routed* (ATLAS's built-in proxy,
 * optionally nginx in front) and whether the app behind that path is
 * *answering*. The card shows the path; the routing panel probes the port.
 */
export default function Portal() {
  const brand = useBrand();
  const [deps, setDeps] = React.useState<Deployment[] | null>(null);
  const [topics, setTopics] = React.useState<Topic[]>([]);
  const [filter, setFilter] = React.useState('');
  const [proxy, setProxy] = React.useState<string | null>(null);
  const [routing, setRouting] = React.useState<RoutingStatus | null>(null);
  const [routingOpen, setRoutingOpen] = React.useState(false);
  const [showNginx, setShowNginx] = React.useState(false);
  const [syncing, setSyncing] = React.useState(false);
  const [copied, setCopied] = React.useState<string | null>(null);
  const { show, node } = useToast();
  const canEdit = auth.canEdit();
  const prefix = getAppPrefix();

  const loadRouting = React.useCallback(async () => {
    try {
      setRouting(await api.get<RoutingStatus>('/api/deployments/proxy-status'));
    } catch { /* the panel keeps the last known state */ }
  }, []);

  const openRouting = async () => {
    setRoutingOpen(true);
    setProxy(null);
    setShowNginx(false);
    try {
      const [cfg] = await Promise.all([
        api.get<string>(`/api/deployments/proxy-config`),
        loadRouting(),
      ]);
      setProxy(cfg);
    } catch (e: any) {
      show(e.message || 'Could not load the routing config', 'bad');
      setRoutingOpen(false);
    }
  };

  // Same call a deploy makes, so a half-applied change is fixable from the UI
  // instead of over ssh.
  const resync = async () => {
    setSyncing(true);
    try {
      const r: any = await api.post('/api/deployments/proxy-sync');
      show(r?.detail || 'Routing re-synced', 'ok');
      await loadRouting();
    } catch (e: any) {
      show(e.message || 'Re-sync failed', 'bad');
    } finally {
      setSyncing(false);
    }
  };

  const copy = (text: string) => {
    navigator.clipboard?.writeText(text)
      .then(() => { setCopied(text); setTimeout(() => setCopied(null), 1400); })
      .catch(() => show('Copy blocked by the browser', 'bad'));
  };

  React.useEffect(() => {
    api.get<Deployment[]>('/api/deployments').then(setDeps).catch(() => setDeps([]));
    api.get<Topic[]>('/api/topics').then(setTopics).catch(() => {});
  }, []);

  const rows = (deps || []).filter((d) => !filter || String(d.topic_id) === filter);
  const live = rows.filter((d) => d.status === 'running');
  const graduated = rows.filter((d) => d.readiness_score >= 80);
  const dead = routing ? routing.expected - routing.live : 0;
  const appUrl = (d: Deployment) => d.url || `/${prefix}/${d.slug}/`;

  return (
    <Shell>
      <PageHeader eyebrow="Portal" title="App portal"
        subtitle={`Everything shipped on this ${brand.tagline.toLowerCase()}, with its rubric score and a live URL under /${prefix}/. This is the surface reviewers open.`}
        actions={
          <div className="flex items-center gap-2">
            {canEdit && (
              <Button variant="outline" icon={<IcCheck size={14} />} onClick={openRouting}>
                App routing
              </Button>
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

        <div className="rounded-xl border border-line bg-paper-deep/50 px-4 py-3 text-[12.5px] text-ink-soft leading-relaxed">
          Each app is reachable at <span className="mono">/{prefix}/&lt;slug&gt;/</span> on this
          domain - the same address as the portal, so there is nothing to open in a firewall, no
          port to guess and no proxy to install. It works the moment the app starts serving.
        </div>

        {!deps && <div className="grid md:grid-cols-2 gap-4">{[0,1].map(i => <Skeleton key={i} className="h-40" />)}</div>}
        {deps && rows.length === 0 && (
          <Card><Empty icon={<IcApps size={20} />} title="No apps published yet"
            body="Apps appear here automatically the moment one is deployed from the Deployment page." /></Card>
        )}

        <div className="grid md:grid-cols-2 gap-4">
          {rows.map((d) => {
            const url = appHref(appUrl(d));
            const running = d.status === 'running';
            return (
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

                {/* The path is the product's promise: stable, guessable, on the
                    main domain. Shown in full so it can be copied as-is. */}
                <button onClick={() => copy(url)}
                  title="Copy the app URL"
                  className={`mb-3.5 flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-left text-[11.5px] mono
                    transition-colors ${copied === url
                      ? 'border-sage-600 bg-[#EAF3EC] text-[#33663F]'
                      : 'border-line bg-paper-deep/40 text-ink-soft hover:bg-paper-deep'}`}>
                  <span className="truncate">{url}</span>
                  <span className="ml-auto shrink-0 text-[10px] font-bold uppercase tracking-wide">
                    {copied === url ? 'copied' : 'copy'}
                  </span>
                </button>

                <div className="mt-auto flex gap-2">
                  {running ? (
                    <a href={url} target="_blank" rel="noreferrer" className="flex-1">
                      <Button size="sm" className="w-full" icon={<IcExternal size={13} />}>Open app</Button>
                    </a>
                  ) : (
                    <Button size="sm" variant="outline" className="flex-1" disabled>Not running</Button>
                  )}
                  {d.whimsical_url && (
                    <a href={d.whimsical_url} target="_blank" rel="noreferrer">
                      <Button size="sm" variant="outline" icon={<IcExternal size={13} />}>Whimsical</Button>
                    </a>
                  )}
                </div>
              </Card>
            );
          })}
        </div>
      </Page>

      <Modal open={routingOpen} onClose={() => setRoutingOpen(false)} title="App routing"
        subtitle={`Every app is served as a virtual directory under /${prefix}/<slug> on this domain. ATLAS routes it itself, so a deploy is reachable without installing anything; nginx stays an option for TLS and hardening.`} wide>
        <div className="space-y-3">
          {!routing ? (
            <div className="text-[13px] text-ink-soft py-4 text-center">Checking how apps are served…</div>
          ) : (
            <div className={`flex items-start gap-3 rounded-xl px-4 py-3 text-[12.5px] leading-snug ${
              routing.builtin.enabled ? 'bg-[#EAF3EC] text-[#33663F]' : 'bg-[#FBF3E2] text-[#8A6420]'}`}>
              <span className="mt-0.5 shrink-0">{routing.builtin.enabled ? <IcCheck size={15} /> : <IcAlert size={15} />}</span>
              <div className="min-w-0">
                {routing.builtin.enabled ? (
                  <>
                    <b>Served by {brand.name} at <span className="mono">{routing.builtin.pattern}</span>.</b>{' '}
                    Each path is forwarded to the app's internal port, HTTP and WebSocket alike, so
                    there is nothing to copy into a proxy and nothing to reload after a deploy.
                    <div className="text-[11.5px] opacity-85 mt-1">
                      {routing.live}/{routing.expected} app(s) answering on their port
                      {dead > 0 ? ` · ${dead} not responding yet (still starting, or stopped)` : ''}
                      {routing.nginx_present ? ' · nginx is also kept in sync on this host' : ''}
                      {routing.installed_at ? ` · vhost installed at ${routing.installed_at}` : ''}
                    </div>
                    {dead > 0 && (
                      <div className="mt-1.5 space-y-0.5">
                        {routing.checks.filter((c) => !c.live).map((c) => (
                          <div key={c.slug} className="text-[11.5px] mono opacity-90 truncate">
                            /{c.path} — {c.detail || 'no response'}
                          </div>
                        ))}
                      </div>
                    )}
                  </>
                ) : (
                  <>
                    <b>The built-in proxy is switched off</b>, so <span className="mono">{routing.builtin.pattern}</span> is
                    expected to be served by an external proxy. Set{' '}
                    <span className="mono">ATLAS_DEPLOY_BUILTIN_PROXY=true</span> to hand routing back to {brand.name}.
                    <div className="text-[11.5px] opacity-85 mt-0.5">{routing.builtin.note}</div>
                  </>
                )}
              </div>
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-2">
            <Button size="sm" variant="outline" icon={<IcRefresh size={13} />}
              onClick={resync} disabled={syncing}>
              {syncing ? 'Re-syncing…' : 'Re-sync routing'}
            </Button>
            <button onClick={() => setShowNginx((v) => !v)}
              className="text-[12px] font-semibold text-sage-700 hover:underline">
              {showNginx ? 'Hide' : 'Show'} nginx config (optional)
            </button>
          </div>

          {showNginx && (
            <>
              <p className="text-[12px] text-ink-muted leading-relaxed">
                Only needed when something must sit in front of {brand.name} — TLS certificates, rate
                limits, or serving the UI bundle from another host. This is the same file a deploy
                writes, with one managed block per app, and it never edits a site it does not own.
              </p>
              {proxy === null
                ? <div className="text-[13px] text-ink-soft py-4 text-center">Loading…</div>
                : (
                  <div className="max-h-[42vh] overflow-auto rounded-xl bg-ink text-[#DDE7DF] p-4 text-[12px] mono whitespace-pre leading-relaxed">
                    {proxy}
                  </div>
                )}
              <div className="flex justify-end">
                <Button size="sm" variant="outline" icon={<IcDownload size={14} />} disabled={!proxy}
                  onClick={() => {
                    if (!proxy) return;
                    const blob = new Blob([proxy], { type: 'text/plain' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url; a.download = 'atlas.conf'; a.click();
                    URL.revokeObjectURL(url);
                  }}>
                  Download atlas.conf
                </Button>
              </div>
            </>
          )}

          <div className="flex justify-end">
            <Button variant="outline" onClick={() => setRoutingOpen(false)}>Close</Button>
          </div>
        </div>
      </Modal>
      {node}
    </Shell>
  );
}
