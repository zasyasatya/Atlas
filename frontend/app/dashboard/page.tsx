'use client';
import Link from 'next/link';
import React from 'react';
import { Activity, api, auth, fmtDate, Run, Topic } from '@/lib/api';
import { Page, PageHeader, Shell } from '../components/Shell';
import { Badge, Button, Card, Empty, Progress, Skeleton, StatusDot } from '../components/UI';
import {
  IcApps, IcArrowRight, IcCpu, IcDatabase, IcFlask, IcGpu, IcPlay, IcRocket,
  IcSlides, IcTarget, IcTrophy, ICON_MAP, IcSpark,
} from '../components/Icons';

export default function Dashboard() {
  const [data, setData] = React.useState<any>(null);
  const [topics, setTopics] = React.useState<Topic[]>([]);
  const [runs, setRuns] = React.useState<Run[]>([]);
  const [feed, setFeed] = React.useState<Activity[]>([]);

  React.useEffect(() => {
    Promise.all([
      api.get<any>('/api/dashboard'),
      api.get<Topic[]>('/api/topics'),
      api.get<Run[]>('/api/runs'),
      api.get<Activity[]>('/api/activity?limit=8'),
    ]).then(([d, t, r, a]) => { setData(d); setTopics(t); setRuns(r); setFeed(a); }).catch(() => {});
  }, []);

  const user = auth.user();
  const c = data?.counters;
  const me = data?.user;
  const lessonPct = me ? Math.round((me.lessons_done / Math.max(me.lessons_total, 1)) * 100) : 0;

  return (
    <Shell>
      <PageHeader
        eyebrow={`${new Date().toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' })}`}
        title={`Hi, ${(user?.full_name || '').split(' ')[0]}`}
        subtitle="Your control room: curriculum progress, compute runs, and every app shipped on this platform."
        actions={
          <>
            <Link href="/playground"><Button variant="outline" icon={<IcFlask size={15} />}>Playground</Button></Link>
            <Link href="/curriculum"><Button icon={<IcArrowRight size={15} />}>Continue learning</Button></Link>
          </>
        }
      />

      <Page className="space-y-6">
        {/* stat row */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3.5">
          <Stat label="Lessons completed" value={me ? `${me.lessons_done}` : '-'}
            suffix={me ? `/ ${me.lessons_total}` : ''} icon={<IcTarget size={16} />}
            foot={<Progress value={lessonPct} tone="sage" />} />
          <Stat label="Notebook runs" value={c?.runs ?? '-'}
            suffix={c ? `${c.gpu_runs} on GPU` : ''} icon={<IcPlay size={16} />} />
          <Stat label="Live apps" value={c?.live_apps ?? '-'}
            suffix={c ? `of ${c.deployments}` : ''} icon={<IcApps size={16} />} />
          <Stat label="Graduation ready" value={c?.graduation_ready ?? '-'}
            suffix="apps at 80%+" icon={<IcTrophy size={16} />} tone="sage" />
        </div>

        <div className="grid lg:grid-cols-3 gap-5 min-w-0">
          {/* topics */}
          <div className="lg:col-span-2 space-y-5 min-w-0">
            <Card className="overflow-hidden">
              <div className="flex items-center justify-between px-5 py-4 border-b border-line">
                <div>
                  <h2 className="text-[15px] font-bold tracking-[-0.01em]">Your topics</h2>
                  <p className="text-[12px] text-ink-muted mt-0.5">Six tracks, each with lessons, a playground and a deliverable.</p>
                </div>
                <Link href="/curriculum" className="text-[12.5px] font-semibold text-sage-700 hover:text-sage-800 flex items-center gap-1">
                  All <IcArrowRight size={13} />
                </Link>
              </div>
              <div className="divide-y divide-line">
                {topics.length === 0 && <div className="p-5 space-y-3">{[0,1,2].map(i => <Skeleton key={i} className="h-14" />)}</div>}
                {topics.map((t) => {
                  const Icon = ICON_MAP[t.icon] || IcSpark;
                  const pct = Math.round((t.completed_lessons / Math.max(t.lesson_count, 1)) * 100);
                  return (
                    <Link key={t.id} href={`/curriculum/view?slug=${t.slug}`}
                      className="flex items-center gap-4 px-5 py-3.5 hover:bg-sage-50/60 transition-colors group">
                      <div className="w-9 h-9 rounded-xl grid place-items-center shrink-0 border"
                        style={{ background: `${t.accent}14`, borderColor: `${t.accent}26`, color: t.accent }}>
                        <Icon size={17} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="text-[13.5px] font-bold text-ink truncate">{t.title}</span>
                          {t.heavy_compute && <Badge tone="warn"><IcGpu size={10} /> GPU</Badge>}
                        </div>
                        <div className="text-[12px] text-ink-muted truncate mt-0.5">{t.subtitle}</div>
                      </div>
                      <div className="hidden sm:flex items-center gap-3 shrink-0 w-[150px]">
                        <Progress value={pct} tone={pct === 100 ? 'ok' : 'sage'} height={5} />
                        <span className="text-[11px] font-bold text-ink-muted tabular-nums w-9 text-right">{pct}%</span>
                      </div>
                      <IcArrowRight size={15} className="text-ink-faint group-hover:text-sage-600 group-hover:translate-x-0.5 transition-all shrink-0" />
                    </Link>
                  );
                })}
              </div>
            </Card>

            {/* runs */}
            <Card className="overflow-hidden">
              <div className="flex items-center justify-between px-5 py-4 border-b border-line">
                <div>
                  <h2 className="text-[15px] font-bold tracking-[-0.01em]">Recent compute runs</h2>
                  <p className="text-[12px] text-ink-muted mt-0.5">CPU worker, Colab GPU and Kaggle GPU jobs.</p>
                </div>
                <Link href="/playground" className="text-[12.5px] font-semibold text-sage-700 hover:text-sage-800 flex items-center gap-1">
                  Open <IcArrowRight size={13} />
                </Link>
              </div>
              {runs.length === 0 ? (
                <Empty icon={<IcPlay size={20} />} title="No runs yet"
                  body="Open a topic playground and launch a notebook. Metrics stream back here automatically."
                  action={<Link href="/playground"><Button size="sm">Go to playground</Button></Link>} />
              ) : (
                <div className="divide-y divide-line">
                  {runs.slice(0, 5).map((r) => (
                    <div key={r.id} className="flex items-center gap-3 px-5 py-3">
                      <StatusDot status={r.status} />
                      <div className="min-w-0 flex-1">
                        <div className="text-[13px] font-semibold text-ink truncate">{r.notebook_title || `Run #${r.id}`}</div>
                        <div className="text-[11.5px] text-ink-muted">
                          {r.user_name} · {fmtDate(r.created_at)}
                          {r.duration_seconds > 0 && ` · ${r.duration_seconds}s`}
                        </div>
                      </div>
                      {Object.keys(r.metrics || {}).length > 0 && (
                        <div className="hidden sm:flex gap-1.5">
                          {Object.entries(r.metrics).slice(0, 2).map(([k, v]) => (
                            <Badge key={k} tone="sage">{k.replace(/_/g, ' ')} {typeof v === 'number' ? (v as number).toFixed(3) : String(v)}</Badge>
                          ))}
                        </div>
                      )}
                      <Badge tone={r.target === 'local_cpu' ? 'neutral' : 'info'}>
                        {r.target === 'local_cpu' ? <IcCpu size={10} /> : <IcGpu size={10} />}
                        {r.target.replace('_', ' ')}
                      </Badge>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </div>

          {/* right rail */}
          <div className="space-y-5">
            <Card className="p-5">
              <div className="flex items-center justify-between mb-3">
                <span className="eyebrow">Your level</span>
                <Badge tone="dark">LVL {me?.level ?? 1}</Badge>
              </div>
              <div className="text-[34px] font-extrabold tracking-[-0.04em] leading-none text-sage-700">
                {me?.xp ?? 0}<span className="text-[15px] text-ink-faint font-bold ml-1.5">XP</span>
              </div>
              <div className="mt-3.5">
                <Progress value={(me?.xp ?? 0) % 200} max={200} tone="sage" />
                <div className="flex justify-between text-[11px] text-ink-muted mt-1.5">
                  <span>{200 - ((me?.xp ?? 0) % 200)} XP to level {(me?.level ?? 1) + 1}</span>
                  <Link href="/leaderboard" className="font-semibold text-sage-700 hover:underline">Leaderboard</Link>
                </div>
              </div>
            </Card>

            <Card className="p-5">
              <div className="eyebrow mb-3.5">Library</div>
              <div className="space-y-2.5">
                <MiniRow icon={<IcDatabase size={14} />} label="Datasets" value={c?.datasets ?? 0} href="/datasets" />
                <MiniRow icon={<IcSlides size={14} />} label="PPT decks" value={c?.decks ?? 0} href="/datasets?tab=decks" />
                <MiniRow icon={<IcFlask size={14} />} label="Notebooks" value={c?.notebooks ?? 0} href="/playground" />
                <MiniRow icon={<IcRocket size={14} />} label="Deployments" value={c?.deployments ?? 0} href="/deployment" />
              </div>
            </Card>

            <Card className="overflow-hidden">
              <div className="px-5 py-4 border-b border-line">
                <div className="eyebrow">Activity</div>
              </div>
              <div className="max-h-[330px] overflow-y-auto">
                {feed.length === 0 && <div className="px-5 py-6 text-[12.5px] text-ink-faint">Nothing yet.</div>}
                {feed.map((a) => (
                  <div key={a.id} className="px-5 py-2.5 border-b border-line last:border-0">
                    <div className="text-[12.5px] text-ink-soft leading-snug">
                      <span className="font-bold text-ink">{a.actor_name}</span> {a.action}
                    </div>
                    <div className="flex items-center gap-1.5 mt-0.5">
                      {a.detail && <span className="text-[11.5px] text-ink-muted truncate">{a.detail}</span>}
                      <span className="text-[11px] text-ink-faint shrink-0 ml-auto">{fmtDate(a.created_at)}</span>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          </div>
        </div>
      </Page>
    </Shell>
  );
}

function Stat({ label, value, suffix, icon, foot, tone }: any) {
  return (
    <Card className="p-4" hover>
      <div className="flex items-start justify-between mb-2.5">
        <span className="text-[11.5px] font-semibold text-ink-muted">{label}</span>
        <span className={`${tone === 'sage' ? 'text-sage-600' : 'text-ink-faint'}`}>{icon}</span>
      </div>
      <div className="flex items-baseline gap-1.5">
        <span className="text-[28px] font-extrabold tracking-[-0.04em] leading-none text-ink tabular-nums">{value}</span>
        {suffix && <span className="text-[11.5px] text-ink-faint font-semibold">{suffix}</span>}
      </div>
      {foot && <div className="mt-3">{foot}</div>}
    </Card>
  );
}

function MiniRow({ icon, label, value, href }: any) {
  return (
    <Link href={href} className="flex items-center gap-2.5 group">
      <span className="text-ink-faint group-hover:text-sage-600 transition-colors">{icon}</span>
      <span className="text-[13px] text-ink-soft group-hover:text-ink flex-1">{label}</span>
      <span className="text-[13px] font-bold text-ink tabular-nums">{value}</span>
    </Link>
  );
}
