'use client';
import React from 'react';
import { api, auth, Role } from '@/lib/api';
import { Page, PageHeader, Shell } from '../components/Shell';
import { Badge, Button, Card, Empty, Field, Input, Modal, Select, Skeleton, useToast } from '../components/UI';
import { IcPlus, IcUsers } from '../components/Icons';

type ManagedUser = {
  id: number;
  email: string;
  full_name: string;
  role: Role;
  cohort: string;
  is_active: boolean;
  created_at: string;
};

const ROLES: { value: Role; label: string }[] = [
  { value: 'admin', label: 'Admin' },
  { value: 'supervisor', label: 'Supervisor' },
  { value: 'intern', label: 'Intern' },
  { value: 'viewer', label: 'Viewer' },
];

const ROLE_TONE: Record<string, string> = {
  admin: 'dark', supervisor: 'sage', intern: 'info', viewer: 'neutral',
};

export default function UsersPage() {
  const [users, setUsers] = React.useState<ManagedUser[] | null>(null);
  const [addOpen, setAddOpen] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [toggling, setToggling] = React.useState<number | null>(null);
  const { show, node } = useToast();

  const me = auth.user();

  // Which roles this operator is allowed to create. Mirrors the backend guard:
  // only an admin may create other admins or supervisors.
  const creatable = React.useMemo(
    () => (me?.role === 'admin' ? ROLES : ROLES.filter((r) => r.value !== 'admin' && r.value !== 'supervisor')),
    [me]);

  const formRef = React.useRef<{ email: string; full_name: string; password: string; role: Role; cohort: string }>({
    email: '', full_name: '', password: '', role: creatable[0]?.value || 'intern', cohort: '',
  });
  const [, force] = React.useReducer((x: number) => x + 1, 0);

  const load = React.useCallback(
    () => api.get<ManagedUser[]>('/api/users').then(setUsers).catch(() => setUsers([])),
    []);
  React.useEffect(() => { load(); }, [load]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const f = formRef.current;
    if (!f.email || !f.full_name || !f.password) {
      show('Email, name and password are required', 'bad');
      return;
    }
    setSaving(true);
    try {
      const created = await api.post<ManagedUser>('/api/users', {
        email: f.email, full_name: f.full_name, password: f.password,
        role: f.role, cohort: f.cohort,
      });
      setUsers((prev) => [created, ...(prev || [])]);
      setAddOpen(false);
      formRef.current = { email: '', full_name: '', password: '', role: creatable[0]?.value || 'intern', cohort: '' };
      show(`${created.full_name} added as ${created.role}`);
    } catch (err: any) {
      show(err.message || 'Could not add user', 'bad');
    } finally {
      setSaving(false);
    }
  };

  const toggleActive = async (u: ManagedUser) => {
    setToggling(u.id);
    try {
      const updated = await api.patch<ManagedUser>(`/api/users/${u.id}`, { is_active: !u.is_active });
      setUsers((prev) => prev?.map((x) => (x.id === u.id ? updated : x)) || null);
      show(updated.is_active ? `${updated.full_name} re-enabled` : `${updated.full_name} disabled`, 'ok');
    } catch (err: any) {
      show(err.message || 'Could not update user', 'bad');
    } finally {
      setToggling(null);
    }
  };

  return (
    <Shell>
      <PageHeader eyebrow="Admin" title="People & accounts"
        subtitle="Create accounts for interns, viewers and supervisors up front, and keep an eye on who has access."
        actions={<Button icon={<IcPlus size={16} />} onClick={() => setAddOpen(true)}>Add user</Button>} />

      <Page className="space-y-5">
        {node}

        {users === null && <Skeleton className="h-64" />}

        {users !== null && (
          users.length === 0 ? (
            <Card>
              <Empty icon={<IcUsers size={20} />} title="No accounts yet"
                body="Add your first user to get the platform populated."
                action={<Button icon={<IcPlus size={16} />} onClick={() => setAddOpen(true)}>Add user</Button>} />
            </Card>
          ) : (
          <Card className="overflow-hidden">
            <div className="px-5 py-4 border-b border-line flex items-center gap-2">
              <IcUsers size={17} className="text-ink-muted" />
              <span className="text-[13px] font-bold text-ink">{users?.length || 0} account(s)</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="bg-paper-deep border-b border-line text-left">
                    <th className="px-4 py-2.5 font-bold text-ink">Name</th>
                    <th className="px-4 py-2.5 font-semibold text-ink-soft">Email</th>
                    <th className="px-4 py-2.5 font-semibold text-ink-soft">Role</th>
                    <th className="px-4 py-2.5 font-semibold text-ink-soft">Cohort</th>
                    <th className="px-4 py-2.5 font-semibold text-ink-soft">Status</th>
                    <th className="px-4 py-2.5 text-right font-semibold text-ink-soft">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {users!.map((u) => (
                    <tr key={u.id} className={u.is_active ? '' : 'opacity-50'}>
                      <td className="px-4 py-3 font-semibold text-ink whitespace-nowrap">
                        {u.full_name}
                        {u.id === me?.id && <Badge tone="sage" className="ml-2">you</Badge>}
                      </td>
                      <td className="px-4 py-3 text-ink-soft">{u.email}</td>
                      <td className="px-4 py-3"><Badge tone={ROLE_TONE[u.role] || 'neutral'} className="capitalize">{u.role}</Badge></td>
                      <td className="px-4 py-3 text-ink-soft">{u.cohort || '—'}</td>
                      <td className="px-4 py-3">
                        <Badge tone={u.is_active ? 'ok' : 'bad'}>{u.is_active ? 'Active' : 'Disabled'}</Badge>
                      </td>
                      <td className="px-4 py-3 text-right whitespace-nowrap">
                        <Button size="sm" variant="ghost" disabled={toggling === u.id || u.id === me?.id}
                          onClick={() => toggleActive(u)}>
                          {u.is_active ? 'Disable' : 'Enable'}
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          )
        )}

        <Modal open={addOpen} onClose={() => setAddOpen(false)} title="Add a user"
          subtitle="The account can sign in immediately with the email and password you set.">
          <form onSubmit={submit} className="space-y-4">
            <Field label="Full name" required>
              <Input required placeholder="e.g. Wayan Jaya"
                defaultValue="" onChange={(e) => { formRef.current.full_name = e.target.value; force(); }} />
            </Field>
            <Field label="Email" required hint="used to sign in">
              <Input required type="email" placeholder="intern@atlas.id"
                onChange={(e) => { formRef.current.email = e.target.value; force(); }} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Password" required hint="min 8 characters">
                <Input required type="password" minLength={8} autoComplete="new-password"
                  onChange={(e) => { formRef.current.password = e.target.value; force(); }} />
              </Field>
              <Field label="Role" required>
                <Select value={formRef.current.role}
                  onChange={(e) => { formRef.current.role = e.target.value as Role; force(); }}>
                  {creatable.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                </Select>
              </Field>
            </div>
            <Field label="Cohort" hint="optional, e.g. Batch 2026-A">
              <Input placeholder="Batch 2026-A"
                onChange={(e) => { formRef.current.cohort = e.target.value; force(); }} />
            </Field>
            <div className="flex justify-end gap-2 pt-2">
              <Button type="button" variant="outline" onClick={() => setAddOpen(false)}>Cancel</Button>
              <Button type="submit" loading={saving} icon={<IcPlus size={16} />}>Create user</Button>
            </div>
          </form>
        </Modal>
      </Page>
    </Shell>
  );
}
