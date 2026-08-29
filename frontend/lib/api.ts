'use client';

// Same-origin by default: the FastAPI monolith serves this bundle and the API.
// Set NEXT_PUBLIC_API_BASE at build time only when the UI is hosted separately
// from the backend (e.g. static files on a CDN, API on another domain).
export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE || '').replace(/\/$/, '');

const TOKEN_KEY = 'atlas_token';
const USER_KEY = 'atlas_user';

export type Role = 'admin' | 'supervisor' | 'intern' | 'viewer';
export interface User { id: number; email: string; full_name: string; role: Role; cohort?: string; }

/**
 * Session storage with graceful degradation.
 *
 * localStorage is unavailable in three situations that all look like "login
 * silently fails and bounces back to /login":
 *   - a sandboxed iframe without allow-same-origin (opaque origin -> SecurityError)
 *   - Safari/Firefox private mode with site data blocked
 *   - browsers configured to block all cookies and storage
 *
 * We try localStorage, then sessionStorage, then fall back to an in-memory map.
 * The memory tier keeps the app fully usable for the current tab (it just does
 * not survive a reload), which is far better than an unbreakable login loop.
 */
const memory = new Map<string, string>();

type Tier = 'local' | 'session' | 'memory';
let tier: Tier | null = null;

function detectTier(): Tier {
  if (tier) return tier;
  if (typeof window === 'undefined') return 'memory';
  for (const [name, store] of [
    ['local', () => window.localStorage],
    ['session', () => window.sessionStorage],
  ] as const) {
    try {
      const s = store();
      const probe = '__atlas_probe__';
      s.setItem(probe, '1');
      s.removeItem(probe);
      tier = name as Tier;
      return tier;
    } catch { /* try the next tier */ }
  }
  tier = 'memory';
  return tier;
}

function backing(): Pick<Storage, 'getItem' | 'setItem' | 'removeItem'> {
  const t = detectTier();
  if (t === 'local') return window.localStorage;
  if (t === 'session') return window.sessionStorage;
  return {
    getItem: (k: string) => (memory.has(k) ? memory.get(k)! : null),
    setItem: (k: string, v: string) => { memory.set(k, v); },
    removeItem: (k: string) => { memory.delete(k); },
  };
}

/** True when the session cannot outlive a page reload (memory tier). */
export function storageIsEphemeral(): boolean {
  return typeof window !== 'undefined' && detectTier() === 'memory';
}

function readStore(key: string): string | null {
  if (typeof window === 'undefined') return null;
  try { return backing().getItem(key); } catch { return null; }
}
function writeStore(key: string, value: string): boolean {
  if (typeof window === 'undefined') return false;
  try { backing().setItem(key, value); return true; } catch { return false; }
}

/**
 * Small UI preferences (sidebar collapsed, and so on).
 *
 * Uses the same tiered storage as the session, so a browser that blocks
 * localStorage degrades to a per-tab or in-memory preference instead of
 * throwing. A preference is never important enough to break a page over.
 */
export const prefs = {
  get: (key: string): string | null => readStore(`atlas.pref.${key}`),
  set: (key: string, value: string): void => { writeStore(`atlas.pref.${key}`, value); },
};

export const auth = {
  token: () => readStore(TOKEN_KEY),
  user: (): User | null => {
    const raw = readStore(USER_KEY);
    if (!raw) return null;
    try { return JSON.parse(raw) as User; } catch { return null; } // corrupt entry != crash
  },
  /** Returns false when the browser refuses to persist (private mode, disabled storage). */
  set(token: string, user: User): boolean {
    const ok = writeStore(TOKEN_KEY, token) && writeStore(USER_KEY, JSON.stringify(user));
    return ok && readStore(TOKEN_KEY) === token;
  },
  clear() {
    if (typeof window === 'undefined') return;
    try {
      backing().removeItem(TOKEN_KEY);
      backing().removeItem(USER_KEY);
    } catch { /* nothing to clear */ }
    memory.delete(TOKEN_KEY);
    memory.delete(USER_KEY);
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
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  } catch {
    // fetch() only rejects on network-level failure: API process down, wrong
    // port, DNS/CORS. Say so plainly instead of surfacing "Failed to fetch".
    throw new Error(
      `Cannot reach the ATLAS API at ${API_BASE || window.location.origin}. ` +
      `Is the backend running? Start it with: python run.py`,
    );
  }
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
