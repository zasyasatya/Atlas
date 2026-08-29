'use client';

export const API_BASE =
  typeof window !== 'undefined' && process.env.NODE_ENV === 'development'
    ? '' // dev: rewritten by next.config proxy
    : '';

const TOKEN_KEY = 'atlas_token';
const USER_KEY = 'atlas_user';

export type Role = 'admin' | 'supervisor' | 'intern' | 'viewer';
export interface User { id: number; email: string; full_name: string; role: Role; cohort?: string; }

export const auth = {
  token: () => (typeof window === 'undefined' ? null : localStorage.getItem(TOKEN_KEY)),
  user: (): User | null => {
    if (typeof window === 'undefined') return null;
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  },
  set(token: string, user: User) {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  },
  clear() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  },
  canEdit(user?: User | null) {
    const u = user ?? auth.user();
    return u?.role === 'admin' || u?.role === 'supervisor';
  },
};

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = auth.token();
  const headers: Record<string, string> = { ...(options.headers as Record<string, string>) };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (options.body && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (res.status === 401) {
    auth.clear();
    if (typeof window !== 'undefined' && !window.location.pathname.includes('login')) {
      window.location.href = '/login';
    }
    throw new Error('Unauthorized');
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try { const j = await res.json(); detail = j.detail || detail; } catch {}
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get('content-type') || '';
  return (ct.includes('application/json') ? res.json() : res.text()) as Promise<T>;
}

export const api = {
  get: <T,>(p: string) => request<T>(p),
  post: <T,>(p: string, body?: any) =>
    request<T>(p, { method: 'POST', body: body instanceof FormData ? body : JSON.stringify(body ?? {}) }),
  put: <T,>(p: string, body?: any) => request<T>(p, { method: 'PUT', body: JSON.stringify(body ?? {}) }),
  patch: <T,>(p: string, body?: any) =>
    request<T>(p, { method: 'PATCH', body: body instanceof FormData ? body : JSON.stringify(body ?? {}) }),
  del: (p: string) => request<void>(p, { method: 'DELETE' }),
};

export interface Topic {
  id: number; slug: string; title: string; subtitle: string; summary: string;
  difficulty: string; estimated_hours: number; accent: string; icon: string;
  heavy_compute: boolean; task_type: string; xp_reward: number; order_index: number;
  status: string; lesson_count: number; completed_lessons: number;
  notebook_count: number; dataset_count: number; deck_count: number;
}
export interface Block { id?: number; block_type: string; payload: any; order_index: number; }
export interface Lesson {
  id: number; topic_id: number; slug: string; title: string; hook: string;
  duration_minutes: number; xp_reward: number; order_index: number; status: string;
  blocks: Block[]; completed: boolean;
}
export interface TopicDetail extends Topic { lessons: Lesson[]; }
export interface Notebook {
  id: number; topic_id: number; slug: string; title: string; description: string;
  default_target: string; requires_gpu: boolean; requirements: string;
  version: number; updated_at: string; cell_count: number;
}
export interface Run {
  id: number; notebook_id: number; topic_id: number; target: string; status: string;
  metrics: Record<string, any>; logs: string; external_url: string; error: string;
  duration_seconds: number; created_at: string; user_name: string; notebook_title: string;
}
export interface Check { rule_id: string; label: string; status: string; detail: string; auto: boolean; }
export interface Deployment {
  id: number; name: string; slug: string; topic_id: number; topic_title: string;
  user_id: number; owner_name: string; framework: string; entrypoint: string;
  status: string; url: string; whimsical_url: string; readiness_score: number;
  published_to_portal: boolean; build_logs: string; created_at: string; checks: Check[];
}
export interface Asset {
  id: number; topic_id: number | null; kind: string; title: string; description: string;
  filename: string; size_bytes: number; version: number; stage: string;
  row_count?: number; column_count?: number; slide_count?: number;
  preview: any; uploader_name: string; created_at: string;
}
export interface Activity {
  id: number; actor_name: string; action: string; entity_type: string;
  detail: string; topic_id: number | null; created_at: string;
}

export function fmtBytes(n: number) {
  if (!n) return '0 B';
  const u = ['B', 'KB', 'MB', 'GB'];
  const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), u.length - 1);
  return `${(n / Math.pow(1024, i)).toFixed(i ? 1 : 0)} ${u[i]}`;
}

export function fmtDate(iso: string) {
  const d = new Date(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}
