'use client';
import React from 'react';
import { api, auth } from '@/lib/api';
import { Page, PageHeader, Shell } from '../components/Shell';
import { Badge, Card, Skeleton } from '../components/UI';
import { IcCheck, IcCloud, IcGpu, IcLock, IcRocket, IcX } from '../components/Icons';

const ENV_GROUPS = [
  {
    title: 'Colab GPU bridge', icon: <IcGpu size={17} />,
    body: 'Push notebooks to a GitHub repo so learners get a true one-click "Open in Colab" link. Without it, ATLAS falls back to URL import, which still works.',
    vars: [
      ['ATLAS_GITHUB_TOKEN', 'GitHub PAT with repo scope'],
      ['ATLAS_COLAB_GITHUB_REPO', 'org/atlas-notebooks'],
      ['ATLAS_COLAB_GITHUB_BRANCH', 'main'],
    ],
    key: 'colab_configured',
  },
  {
    title: 'Kaggle GPU bridge', icon: <IcCloud size={17} />,
    body: 'Fully headless GPU training — ATLAS submits the kernel and polls results. 30 GPU hours per week, free.',
    vars: [['ATLAS_KAGGLE_USERNAME', 'from kaggle.json'], ['ATLAS_KAGGLE_KEY', 'from kaggle.json']],
    key: 'kaggle_configured',
  },
  {
    title: 'Deployment driver', icon: <IcRocket size={17} />,
    body: 'local_process runs apps as child processes (great for demos). coolify deploys through the Coolify API. manifest only writes the Dockerfile.',
    vars: [
      ['ATLAS_DEPLOY_DRIVER', 'local_process | coolify | manifest'],
      ['ATLAS_COOLIFY_BASE_URL', 'https://coolify.yourdomain.com'],
      ['ATLAS_COOLIFY_TOKEN', 'API token'],
      ['ATLAS_COOLIFY_PROJECT_UUID', 'target project'],
      ['ATLAS_COOLIFY_SERVER_UUID', 'target server'],
    ],
  },
  {
    title: 'Google SSO', icon: <IcLock size={17} />,
    body: 'Optional. Interns can sign in with a corporate Google account; the same consent covers Drive/Colab access.',
    vars: [['ATLAS_GOOGLE_CLIENT_ID', 'OAuth client id'], ['ATLAS_GOOGLE_CLIENT_SECRET', 'OAuth secret']],
  },
  {
    title: 'Platform', icon: <IcCheck size={17} />,
    body: 'Core settings. ATLAS_PUBLIC_BASE_URL matters most — remote notebooks call back to this address.',
    vars: [
      ['ATLAS_PUBLIC_BASE_URL', 'https://atlas.yourdomain.com'],
      ['ATLAS_SECRET_KEY', 'JWT signing key (change in production)'],
      ['ATLAS_DATABASE_URL', 'defaults to SQLite in ./storage'],
    ],
  },
];

export default function Settings() {
  const [cfg, setCfg] = React.useState<any>(null);
  const user = auth.user();
  React.useEffect(() => { api.get<any>('/api/config').then(setCfg).catch(() => {}); }, []);

  return (
    <Shell>
      <PageHeader eyebrow="Settings" title="Platform configuration"
        subtitle="ATLAS reads everything from environment variables, so the same image runs locally and on Coolify without code changes." />
      <Page className="space-y-5">
        <Card className="p-5">
          <div className="eyebrow mb-3">Signed in as</div>
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-xl bg-sage-600 text-white grid place-items-center text-[14px] font-bold">
              {(user?.full_name || 'A').split(' ').map(s => s[0]).slice(0, 2).join('')}
            </div>
            <div>
              <div className="text-[15px] font-bold text-ink">{user?.full_name}</div>
              <div className="text-[12.5px] text-ink-muted">{user?.email}</div>
            </div>
            <Badge tone="sage" className="ml-auto capitalize">{user?.role}</Badge>
          </div>
        </Card>

        {!cfg && <Skeleton className="h-32" />}

        {ENV_GROUPS.map((g) => {
          const on = g.key ? cfg?.[g.key] : undefined;
          return (
            <Card key={g.title} className="p-5">
              <div className="flex items-start gap-3 mb-3">
                <div className="w-9 h-9 rounded-xl bg-paper-deep grid place-items-center shrink-0 text-ink-muted">{g.icon}</div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <h3 className="text-[15px] font-bold text-ink">{g.title}</h3>
                    {on !== undefined && (
                      <Badge tone={on ? 'ok' : 'neutral'}>
                        {on ? <><IcCheck size={10} /> configured</> : <><IcX size={10} /> not set</>}
                      </Badge>
                    )}
                  </div>
                  <p className="text-[13px] text-ink-soft mt-1 leading-relaxed">{g.body}</p>
                </div>
              </div>
              <div className="space-y-1">
                {g.vars.map(([k, v]) => (
                  <div key={k} className="flex flex-wrap items-baseline gap-2 px-3 py-1.5 rounded-lg bg-paper-deep/60">
                    <code className="text-[12px] font-bold text-ink mono">{k}</code>
                    <span className="text-[11.5px] text-ink-muted">{v}</span>
                  </div>
                ))}
              </div>
            </Card>
          );
        })}

        <Card className="p-5">
          <div className="eyebrow mb-2">Current runtime</div>
          <div className="grid sm:grid-cols-2 gap-2">
            {[['Deploy driver', cfg?.deploy_driver], ['Colab', cfg?.colab_configured ? 'ready' : 'fallback mode'],
              ['Kaggle', cfg?.kaggle_configured ? 'ready' : 'not configured'], ['Google SSO', cfg?.google_enabled ? 'ready' : 'not configured']]
              .map(([k, v]) => (
              <div key={k as string} className="flex items-center justify-between px-3 py-2 rounded-lg bg-paper-deep/60">
                <span className="text-[12.5px] text-ink-soft">{k}</span>
                <span className="text-[12.5px] font-bold text-ink mono">{String(v ?? '-')}</span>
              </div>
            ))}
          </div>
        </Card>
      </Page>
    </Shell>
  );
}
