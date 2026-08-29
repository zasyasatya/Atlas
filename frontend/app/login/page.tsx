'use client';
import { useRouter } from 'next/navigation';
import React from 'react';
import { api, auth, storageIsEphemeral } from '@/lib/api';
import { Button, Field, Input, useToast } from '../components/UI';
import { Logo } from '../components/Shell';
import { IcArrowRight, IcLock } from '../components/Icons';

const DEMO = [
  { email: 'supervisor@atlas.id', password: 'supervisor123', role: 'Supervisor', note: 'authors content, reviews apps' },
  { email: 'intern@atlas.id', password: 'intern123', role: 'Intern', note: 'learns, runs notebooks, ships apps' },
  { email: 'admin@atlas.id', password: 'admin123', role: 'Admin', note: 'full platform control' },
];

export default function Login() {
  const router = useRouter();
  const { show, node } = useToast();
  const [email, setEmail] = React.useState('supervisor@atlas.id');
  const [password, setPassword] = React.useState('supervisor123');
  const [loading, setLoading] = React.useState(false);
  const [googleId, setGoogleId] = React.useState('');

  React.useEffect(() => {
    api.get<any>('/api/config').then((c) => setGoogleId(c.google_client_id || '')).catch(() => {});
  }, []);

  const [ephemeral, setEphemeral] = React.useState(false);

  // Already signed in? Skip the form.
  React.useEffect(() => {
    if (auth.token() && auth.user()) router.replace('/dashboard');
    setEphemeral(storageIsEphemeral());
  }, [router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (loading) return;
    setLoading(true);
    try {
      const res = await api.post<any>('/api/auth/login', { email, password });
      if (!auth.set(res.access_token, res.user)) {
        show('Cannot save your session: browser storage is blocked. Disable private mode or allow site data.', 'bad');
        setLoading(false);
        return;
      }
      if (storageIsEphemeral()) {
        // Storage is memory-only (sandboxed iframe / blocked site data). A full
        // page load would discard the token and bounce us back here, so stay in
        // the same document and navigate client-side.
        router.push('/dashboard');
      } else {
        // Persisted: a hard navigation guarantees the dashboard boots with the
        // token already committed.
        window.location.assign('/dashboard');
      }
    } catch (err: any) {
      show(err.message || 'Login failed', 'bad');
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex">
      {/* left: form */}
      <div className="flex-1 flex items-center justify-center px-5 py-10">
        <div className="w-full max-w-[380px]">
          <div className="flex items-center gap-2.5 mb-9">
            <Logo size={34} />
            <div>
              <div className="font-extrabold text-[17px] tracking-[-0.02em] leading-none">ATLAS</div>
              <div className="text-[10px] text-ink-faint mt-1 tracking-wide">AI INTERNSHIP OS</div>
            </div>
          </div>

          <div className="eyebrow mb-2.5">Sign in</div>
          <h1 className="text-[32px] font-extrabold tracking-[-0.035em] leading-[1.08] mb-2">
            Welcome back
          </h1>
          <p className="text-[15px] text-ink-soft mb-7 leading-relaxed">
            Learn the architecture, train on borrowed GPUs, ship the app.
          </p>

          {ephemeral && (
            <div className="mb-4 rounded-xl border border-signal-warn/30 bg-signal-warn/10 px-3.5 py-2.5 text-[12.5px] text-ink-soft leading-relaxed">
              Your browser is blocking site storage, so this session will end when
              you reload. Open ATLAS in a normal browser tab to stay signed in.
            </div>
          )}
          <form onSubmit={submit} method="post" action="#" className="space-y-4">
            <Field label="Email">
              <Input type="email" name="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
            </Field>
            <Field label="Password">
              <Input type="password" name="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password" />
            </Field>
            <Button type="submit" size="lg" loading={loading} className="w-full" icon={!loading && <IcArrowRight size={16} />}>
              Sign in
            </Button>
          </form>

          <div className="flex items-center gap-3 my-6">
            <div className="flex-1 h-px bg-line" />
            <span className="text-[11px] text-ink-faint font-semibold">OR</span>
            <div className="flex-1 h-px bg-line" />
          </div>

          <Button variant="outline" size="lg" className="w-full"
            onClick={() => show(googleId ? 'Redirecting to Google...' : 'Set ATLAS_GOOGLE_CLIENT_ID to enable Google SSO', googleId ? 'ok' : 'warn')}
            icon={<GoogleMark />}>
            Continue with Google
          </Button>

          <div className="mt-8 pt-6 border-t border-line">
            <div className="flex items-center gap-1.5 text-[11px] font-semibold text-ink-faint mb-3">
              <IcLock size={12} /> DEMO ACCOUNTS
            </div>
            <div className="space-y-1.5">
              {DEMO.map((d) => (
                <button key={d.email} type="button"
                  onClick={() => { setEmail(d.email); setPassword(d.password); }}
                  className="w-full text-left px-3 py-2 rounded-xl border border-line hover:border-sage-300 hover:bg-sage-50 transition-colors group">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[13px] font-bold text-ink">{d.role}</span>
                    <span className="text-[11px] text-ink-faint group-hover:text-sage-600 mono">{d.email}</span>
                  </div>
                  <div className="text-[11px] text-ink-muted mt-0.5">{d.note}</div>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* right: decorative panel echoing the reference dot-matrix */}
      <div className="hidden lg:block flex-1 relative bg-gradient-to-br from-sage-50 via-paper to-paper-deep border-l border-line overflow-hidden">
        <div className="absolute inset-0 grid-canvas opacity-70" />
        <div className="relative h-full flex flex-col justify-center px-14 max-w-[560px]">
          <DotDiagram />
          <div className="eyebrow mb-3">END TO END</div>
          <h2 className="text-[30px] font-extrabold tracking-[-0.03em] leading-[1.12] mb-4 text-ink">
            From "what is a neural network" to a deployed app with a public URL.
          </h2>
          <p className="text-[15px] text-ink-soft leading-relaxed mb-7">
            Supervisors author game-style lessons without touching code. Interns run heavy
            vision training on borrowed Colab and Kaggle GPUs, then one-click deploy a
            Streamlit or Gradio app that is automatically graded against the graduation rubric.
          </p>
          <div className="grid grid-cols-3 gap-3">
            {[['6', 'topics'], ['3', 'compute targets'], ['5', 'rubric checks']].map(([n, l]) => (
              <div key={l} className="card px-3.5 py-3">
                <div className="text-[22px] font-extrabold tracking-[-0.03em] text-sage-700">{n}</div>
                <div className="text-[11px] text-ink-muted mt-0.5">{l}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function GoogleMark() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24">
      <path fill="#4285F4" d="M22.6 12.2c0-.7-.1-1.4-.2-2H12v4h6a5 5 0 0 1-2.2 3.3v2.8h3.6c2.1-2 3.2-4.8 3.2-8.1z"/>
      <path fill="#34A853" d="M12 23c2.9 0 5.4-1 7.2-2.7l-3.6-2.8c-1 .7-2.2 1-3.6 1-2.8 0-5.2-1.9-6-4.4H2.3v2.9A11 11 0 0 0 12 23z"/>
      <path fill="#FBBC05" d="M6 14.1a6.6 6.6 0 0 1 0-4.2V7H2.3a11 11 0 0 0 0 9.9L6 14.1z"/>
      <path fill="#EA4335" d="M12 5.4c1.6 0 3 .5 4.1 1.6l3.1-3.1A11 11 0 0 0 2.3 7L6 9.9c.8-2.5 3.2-4.5 6-4.5z"/>
    </svg>
  );
}

/** Dot-matrix motif lifted from the reference screenshot. Deterministic, SSR-safe. */
function DotDiagram() {
  const dots: JSX.Element[] = [];
  const rects = [
    { x: 60, y: 8, w: 90, h: 34 },
    { x: 8, y: 54, w: 250, h: 46 },
    { x: 8, y: 108, w: 250, h: 46 },
  ];
  // integer-quantised pseudo-random offsets keep server and client markup identical
  const jitter = (seed: number) => ((Math.sin(seed * 12.9898) * 43758.5453) % 1 + 1) % 1;
  let k = 0;
  rects.forEach((r) => {
    const per = 2.6;
    const along = (x1: number, y1: number, x2: number, y2: number) => {
      const len = Math.hypot(x2 - x1, y2 - y1);
      const n = Math.max(Math.floor(len / per), 1);
      for (let i = 0; i <= n; i++) {
        const t = i / n;
        const jx = jitter(k + 1);
        const jy = jitter(k + 101);
        const cx = (x1 + (x2 - x1) * t + jx * 2.2).toFixed(2);
        const cy = (y1 + (y2 - y1) * t + jy * 2.2).toFixed(2);
        const op = (0.55 + (jx % 0.4)).toFixed(2);
        dots.push(<circle key={k} cx={cx} cy={cy} r="1.05" fill="#94B69D" opacity={op} />);
        k++;
      }
    };
    along(r.x, r.y, r.x + r.w, r.y);
    along(r.x + r.w, r.y, r.x + r.w, r.y + r.h);
    along(r.x + r.w, r.y + r.h, r.x, r.y + r.h);
    along(r.x, r.y + r.h, r.x, r.y);
  });
  return (
    <svg viewBox="0 0 270 165" className="w-full max-w-[330px] mb-9 opacity-90">
      {dots}
    </svg>
  );
}
