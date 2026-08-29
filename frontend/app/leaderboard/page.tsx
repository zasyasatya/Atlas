'use client';
import React from 'react';
import { api } from '@/lib/api';
import { Page, PageHeader, Shell } from '../components/Shell';
import { Badge, Card, Empty, Skeleton } from '../components/UI';
import { IcTrophy } from '../components/Icons';

export default function Leaderboard() {
  const [rows, setRows] = React.useState<any[] | null>(null);
  React.useEffect(() => { api.get<any[]>('/api/leaderboard').then(setRows).catch(() => setRows([])); }, []);

  return (
    <Shell>
      <PageHeader eyebrow="Cohort" title="Leaderboard"
        subtitle="XP earned by completing curriculum stages. Progress, not perfection." />
      <Page>
        <Card className="overflow-hidden">
          {!rows && <div className="p-5 space-y-3">{[0,1,2].map(i => <Skeleton key={i} className="h-12" />)}</div>}
          {rows && rows.length === 0 && (
            <Empty icon={<IcTrophy size={20} />} title="Nobody has scored yet"
              body="Complete a curriculum stage to appear on the board." />
          )}
          <div className="divide-y divide-line">
            {rows?.map((r, i) => (
              <div key={r.name} className="flex items-center gap-4 px-5 py-3.5">
                <span className={`w-8 h-8 rounded-xl grid place-items-center text-[13px] font-extrabold shrink-0 ${
                  i === 0 ? 'bg-[#8C7A4F] text-white' : i === 1 ? 'bg-line-strong text-ink' :
                  i === 2 ? 'bg-[#8C5B4F] text-white' : 'bg-paper-deep text-ink-muted'}`}>
                  {i + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-[14px] font-bold text-ink">{r.name}</div>
                  <div className="text-[12px] text-ink-muted">{r.cohort || 'no cohort'}</div>
                </div>
                <Badge tone="dark">LVL {r.level}</Badge>
                <span className="text-[16px] font-extrabold tabular-nums text-sage-700 w-16 text-right">{r.xp}</span>
              </div>
            ))}
          </div>
        </Card>
      </Page>
    </Shell>
  );
}
