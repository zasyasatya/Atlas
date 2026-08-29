'use client';
/**
 * Supervisor-side control over who may see which topic.
 *
 * The model is a grid of checkboxes rather than a list of individual grants,
 * because the question a supervisor actually asks is "what is this intern
 * working on" - not "which assignment rows exist". Toggling saves the whole
 * row via PUT /api/assignments/bulk, so the UI never has to reconcile creates
 * against deletes.
 */
import React from 'react';
import { api, Topic } from '@/lib/api';
import { Badge, Button, Card, Empty, Skeleton, useToast } from './UI';
import { IcCheck, IcLock, IcUsers } from './Icons';

type Assignable = {
  id: number;
  email: string;
  full_name: string;
  cohort: string;
  is_active: boolean;
  topic_ids: number[];
};

export function AssignmentManager({ topics }: { topics: Topic[] }) {
  const [users, setUsers] = React.useState<Assignable[] | null>(null);
  const [saving, setSaving] = React.useState<number | null>(null);
  const { show, node } = useToast();

  const load = React.useCallback(
    () => api.get<Assignable[]>('/api/assignable-users').then(setUsers).catch(() => setUsers([])),
    []);
  React.useEffect(() => { load(); }, [load]);

  const toggle = async (user: Assignable, topicId: number) => {
    const next = user.topic_ids.includes(topicId)
      ? user.topic_ids.filter((t) => t !== topicId)
      : [...user.topic_ids, topicId];

    // Optimistic: the checkbox should respond immediately.
    setUsers((prev) => prev?.map((u) => (u.id === user.id ? { ...u, topic_ids: next } : u)) || null);
    setSaving(user.id);
    try {
      await api.put('/api/assignments/bulk', { user_id: user.id, topic_ids: next });
      show(`${user.full_name}: ${next.length} topic${next.length === 1 ? '' : 's'} assigned`);
    } catch {
      show('Could not save - reloading', 'bad');
      load();
    } finally {
      setSaving(null);
    }
  };

  const setAll = async (user: Assignable, all: boolean) => {
    const next = all ? topics.map((t) => t.id) : [];
    setUsers((prev) => prev?.map((u) => (u.id === user.id ? { ...u, topic_ids: next } : u)) || null);
    setSaving(user.id);
    try {
      await api.put('/api/assignments/bulk', { user_id: user.id, topic_ids: next });
      show(`${user.full_name}: ${next.length} topic${next.length === 1 ? '' : 's'} assigned`);
    } catch {
      show('Could not save - reloading', 'bad');
      load();
    } finally {
      setSaving(null);
    }
  };

  if (!users) return <Skeleton className="h-56" />;

  return (
    <Card className="overflow-hidden">
      {node}
      <div className="px-5 py-4 border-b border-line flex items-start gap-3">
        <div className="w-9 h-9 rounded-xl grid place-items-center shrink-0 bg-sage-50 border border-sage-200 text-sage-600">
          <IcUsers size={17} />
        </div>
        <div className="min-w-0">
          <div className="text-[15px] font-extrabold tracking-[-0.02em] text-ink">Topic assignments</div>
          <p className="text-[12.5px] text-ink-muted mt-0.5 leading-relaxed">
            In production an intern only sees the topics you tick here - the curriculum,
            its notebook, its datasets and its reference pipeline. In development
            everything stays visible so the platform is explorable.
          </p>
        </div>
      </div>

      {users.length === 0 ? (
        <Empty icon={<IcUsers size={20} />} title="No interns yet"
          body="Interns appear here as soon as they sign up or are created by an admin." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[12.5px]">
            <thead>
              <tr className="bg-paper-deep border-b border-line">
                <th className="px-4 py-2.5 text-left font-bold text-ink whitespace-nowrap sticky left-0 bg-paper-deep">
                  Intern
                </th>
                {topics.map((t) => (
                  <th key={t.id} className="px-2 py-2.5 text-center font-semibold text-ink-soft"
                    style={{ minWidth: 92 }}>
                    <div className="flex flex-col items-center gap-1">
                      <span className="w-2 h-2 rounded-full" style={{ background: t.accent }} />
                      <span className="text-[10.5px] leading-tight max-w-[86px]">{t.title}</span>
                    </div>
                  </th>
                ))}
                <th className="px-3 py-2.5 text-right font-bold text-ink whitespace-nowrap">All</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {users.map((u) => {
                const busy = saving === u.id;
                return (
                  <tr key={u.id} className={busy ? 'opacity-60' : ''}>
                    <td className="px-4 py-2.5 sticky left-0 bg-white">
                      <div className="font-semibold text-ink whitespace-nowrap">{u.full_name}</div>
                      <div className="text-[11px] text-ink-faint whitespace-nowrap">{u.email}</div>
                    </td>
                    {topics.map((t) => {
                      const on = u.topic_ids.includes(t.id);
                      return (
                        <td key={t.id} className="px-2 py-2.5 text-center">
                          <button
                            type="button"
                            aria-label={`${on ? 'Unassign' : 'Assign'} ${t.title} for ${u.full_name}`}
                            aria-pressed={on}
                            disabled={busy}
                            onClick={() => toggle(u, t.id)}
                            className="w-5 h-5 rounded-md border grid place-items-center transition-colors mx-auto"
                            style={{
                              background: on ? t.accent : '#fff',
                              borderColor: on ? t.accent : '#D7DED7',
                            }}>
                            {on && <IcCheck size={12} className="text-white" />}
                          </button>
                        </td>
                      );
                    })}
                    <td className="px-3 py-2.5 text-right whitespace-nowrap">
                      <button type="button" disabled={busy}
                        onClick={() => setAll(u, u.topic_ids.length < topics.length)}
                        className="text-[11px] font-bold text-sage-600 hover:underline">
                        {u.topic_ids.length < topics.length ? 'Assign all' : 'Clear'}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

/** Shown to an intern in production when nothing has been assigned to them. */
export function NoAssignments() {
  return (
    <Card className="p-8 text-center">
      <div className="w-12 h-12 rounded-2xl grid place-items-center mx-auto mb-3.5 bg-paper-deep border border-line text-ink-faint">
        <IcLock size={22} />
      </div>
      <div className="text-[17px] font-extrabold tracking-[-0.02em] text-ink mb-1.5">
        No topics assigned yet
      </div>
      <p className="text-[13px] text-ink-muted max-w-md mx-auto leading-relaxed">
        Your supervisor decides which parts of the programme you work on. As soon as a
        topic is assigned to you it appears here, together with its notebook, datasets
        and reference pipeline.
      </p>
      <div className="mt-4">
        <Badge tone="info">Waiting for supervisor</Badge>
      </div>
    </Card>
  );
}
