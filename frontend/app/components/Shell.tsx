'use client';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import React from 'react';
import { auth, storageIsEphemeral, User } from '@/lib/api';
import {
  IcApps, IcBook, IcDatabase, IcFlask, IcGrid, IcLogout, IcMenu, IcRocket,
  IcCode, IcSettings, IcTrophy, IcX,
} from './Icons';

const NAV = [
  { href: '/dashboard', label: 'Dashboard', icon: IcGrid },
  { href: '/curriculum', label: 'Curriculum', icon: IcBook },
  { href: '/playground', label: 'Playground', icon: IcFlask },
  { href: '/pipelines', label: 'Pipeline Library', icon: IcCode },
  { href: '/datasets', label: 'Datasets & Decks', icon: IcDatabase },
  { href: '/deployment', label: 'Deployment', icon: IcRocket },
  { href: '/portal', label: 'App Portal', icon: IcApps },
];

const NAV_BOTTOM = [
  { href: '/leaderboard', label: 'Leaderboard', icon: IcTrophy },
  { href: '/settings', label: 'Settings', icon: IcSettings },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = React.useState<User | null>(null);
  const [open, setOpen] = React.useState(false);
  const [ready, setReady] = React.useState(false);

  React.useEffect(() => {
    // Require BOTH: a stored user with no token yields 401s on every request,
    // which would bounce back here anyway — treat it as logged out up front.
    const u = auth.user();
    const t = auth.token();
    if (!u || !t) {
      auth.clear();
      // On the memory tier a hard navigation would discard the session, so use
      // the client router; otherwise a full replace avoids a render race where
      // the protected page keeps firing 401s during the transition.
      if (storageIsEphemeral()) router.replace('/login');
      else window.location.replace('/login');
      return;
    }
    setUser(u);
    setReady(true);
  }, [router]);

  React.useEffect(() => { setOpen(false); }, [pathname]);

  if (!ready) {
    return (
      <div className="min-h-screen grid place-items-center bg-paper">
        <div className="text-[13px] text-ink-faint">Loading ATLAS...</div>
      </div>
    );
  }

  const initials = (user?.full_name || 'A').split(' ').map((s) => s[0]).slice(0, 2).join('').toUpperCase();

  const NavLink = ({ href, label, icon: Icon }: any) => {
    const active = pathname === href || (href !== '/dashboard' && pathname.startsWith(href));
    return (
      <Link href={href}
        className={`group flex items-center gap-3 px-3 py-2 rounded-xl text-[13.5px] font-semibold transition-all duration-150 ${
          active ? 'bg-sage-600 text-white shadow-soft' : 'text-ink-soft hover:bg-sage-50 hover:text-sage-800'}`}>
        <Icon size={17} className={active ? 'text-white' : 'text-ink-faint group-hover:text-sage-600'} />
        <span>{label}</span>
      </Link>
    );
  };

  return (
    <div className="min-h-screen bg-paper">
      {/* mobile top bar */}
      <div className="lg:hidden sticky top-0 z-40 flex items-center justify-between px-4 h-14 bg-white/90 backdrop-blur border-b border-line">
        <Link href="/dashboard" className="flex items-center gap-2">
          <Logo />
          <span className="font-extrabold tracking-[-0.02em]">ATLAS</span>
        </Link>
        <button onClick={() => setOpen(!open)} className="p-2 rounded-lg text-ink-soft hover:bg-paper-deep">
          {open ? <IcX size={20} /> : <IcMenu size={20} />}
        </button>
      </div>

      <div className="flex w-full">
        {/* sidebar */}
        <aside className={`fixed lg:sticky top-0 z-40 h-screen w-[248px] shrink-0 bg-white border-r border-line flex flex-col transition-transform duration-200 ${
          open ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}`}>
          <div className="px-5 pt-6 pb-5">
            <Link href="/dashboard" className="flex items-center gap-2.5">
              <Logo />
              <div>
                <div className="font-extrabold text-[15px] tracking-[-0.02em] leading-none">ATLAS</div>
                <div className="text-[10px] text-ink-faint mt-1 tracking-wide">INTERNSHIP OS</div>
              </div>
            </Link>
          </div>

          <div className="px-5 pb-4">
            <div className="flex items-center gap-2.5 p-2.5 rounded-xl bg-paper-deep">
              <div className="w-8 h-8 rounded-lg bg-sage-600 text-white grid place-items-center text-[12px] font-bold shrink-0">
                {initials}
              </div>
              <div className="min-w-0">
                <div className="text-[13px] font-bold text-ink truncate leading-tight">{user?.full_name}</div>
                <div className="text-[11px] text-ink-faint capitalize">{user?.role}</div>
              </div>
            </div>
          </div>

          <nav className="flex-1 px-3 space-y-0.5 overflow-y-auto">
            {NAV.map((n) => <NavLink key={n.href} {...n} />)}
            <div className="pt-4 mt-4 border-t border-line space-y-0.5">
              {NAV_BOTTOM.map((n) => <NavLink key={n.href} {...n} />)}
            </div>
          </nav>

          <div className="p-3 border-t border-line">
            <button onClick={() => { auth.clear(); router.push('/login'); }}
              className="w-full flex items-center gap-3 px-3 py-2 rounded-xl text-[13.5px] font-semibold text-ink-muted hover:bg-paper-deep hover:text-signal-bad transition-colors">
              <IcLogout size={17} />
              Log out
            </button>
          </div>
        </aside>

        {open && <div className="lg:hidden fixed inset-0 z-30 bg-ink/20" onClick={() => setOpen(false)} />}

        <main className="flex-1 min-w-0 w-full overflow-x-hidden">{children}</main>
      </div>
    </div>
  );
}

export function Logo({ size = 30 }: { size?: number }) {
  return (
    <div className="rounded-xl bg-ink grid place-items-center shrink-0" style={{ width: size, height: size }}>
      <svg width={size * 0.55} height={size * 0.55} viewBox="0 0 24 24" fill="none">
        <path d="M12 2 3 20h4l5-10 5 10h4L12 2z" fill="#94B69D" />
        <circle cx="12" cy="14" r="2.4" fill="#F6F8F6" />
      </svg>
    </div>
  );
}

/** Page header matching the reference: eyebrow, big title, supporting line. */
export function PageHeader({ eyebrow, title, subtitle, actions, children }: any) {
  return (
    <div className="border-b border-line bg-gradient-to-b from-white to-paper">
      <div className="grid-canvas">
        <div className="max-w-[1180px] mx-auto px-5 sm:px-8 py-8 sm:py-10">
          <div className="flex flex-wrap items-end justify-between gap-5">
            <div className="min-w-0">
              {eyebrow && <div className="eyebrow mb-2.5">{eyebrow}</div>}
              <h1 className="text-[30px] sm:text-[38px] font-extrabold tracking-[-0.035em] leading-[1.05] text-ink">
                {title}
              </h1>
              {subtitle && (
                <p className="mt-2.5 text-[15px] sm:text-[17px] text-ink-soft leading-relaxed max-w-2xl">
                  {subtitle}
                </p>
              )}
            </div>
            {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
          </div>
          {children}
        </div>
      </div>
    </div>
  );
}

export function Page({ children, className = '' }: any) {
  return <div className={`max-w-[1180px] mx-auto px-5 sm:px-8 py-7 ${className}`}>{children}</div>;
}
