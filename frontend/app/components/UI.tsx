'use client';
import React from 'react';
import { IcAlert, IcCheck, IcX } from './Icons';

export function Eyebrow({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <div className={`eyebrow ${className}`}>{children}</div>;
}

export function Card({ children, className = '', hover = false, ...rest }: any) {
  return (
    <div className={`card shadow-soft ${hover ? 'transition-all duration-200 hover:shadow-lift hover:-translate-y-0.5' : ''} ${className}`} {...rest}>
      {children}
    </div>
  );
}

type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'ghost' | 'outline' | 'danger' | 'subtle';
  size?: 'sm' | 'md' | 'lg';
  icon?: React.ReactNode;
  loading?: boolean;
};

export function Button({ variant = 'primary', size = 'md', icon, loading, children, className = '', disabled, ...rest }: BtnProps) {
  const base = 'inline-flex items-center justify-center gap-2 font-semibold rounded-xl transition-all duration-150 disabled:opacity-45 disabled:cursor-not-allowed select-none';
  const sizes = { sm: 'text-[13px] px-3 py-1.5', md: 'text-sm px-4 py-2.5', lg: 'text-[15px] px-5 py-3' };
  const variants = {
    primary: 'bg-sage-600 text-white hover:bg-sage-700 active:bg-sage-800 shadow-soft',
    ghost: 'text-ink-soft hover:bg-sage-50 hover:text-ink',
    outline: 'border border-line-strong text-ink-soft hover:border-sage-400 hover:text-sage-700 hover:bg-sage-50 bg-white',
    danger: 'bg-signal-bad text-white hover:opacity-90',
    subtle: 'bg-sage-100 text-sage-800 hover:bg-sage-200',
  };
  return (
    <button className={`${base} ${sizes[size]} ${variants[variant]} ${className}`} disabled={disabled || loading} {...rest}>
      {loading ? <Spinner /> : icon}
      {children}
    </button>
  );
}

export function Spinner({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" className="animate-spin">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" fill="none" opacity="0.25" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" fill="none" strokeLinecap="round" />
    </svg>
  );
}

export function Badge({ tone = 'neutral', children, className = '' }: { tone?: string; children: React.ReactNode; className?: string }) {
  const tones: Record<string, string> = {
    neutral: 'bg-paper-deep text-ink-muted border-line',
    sage: 'bg-sage-100 text-sage-800 border-sage-200',
    ok: 'bg-[#EAF3EC] text-[#33663F] border-[#CFE3D4]',
    warn: 'bg-[#FBF3E2] text-[#8A6420] border-[#EEDFBE]',
    bad: 'bg-[#FAEBE8] text-[#8F3B2C] border-[#EED2CB]',
    info: 'bg-[#EAF1F4] text-[#3C6373] border-[#CFDFE6]',
    dark: 'bg-ink text-white border-ink',
  };
  return (
    <span className={`inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full border ${tones[tone] || tones.neutral} ${className}`}>
      {children}
    </span>
  );
}

export function StatusDot({ status }: { status: string }) {
  const map: Record<string, string> = {
    succeeded: 'bg-signal-ok', running: 'bg-signal-info animate-pulseSoft',
    queued: 'bg-signal-warn animate-pulseSoft', pending: 'bg-signal-idle',
    failed: 'bg-signal-bad', cancelled: 'bg-signal-idle',
    draft: 'bg-signal-idle', building: 'bg-signal-warn animate-pulseSoft',
    stopped: 'bg-signal-idle', pass: 'bg-signal-ok', warn: 'bg-signal-warn', bad: 'bg-signal-bad',
  };
  return <span className={`inline-block w-1.5 h-1.5 rounded-full ${map[status] || 'bg-signal-idle'}`} />;
}

export function Progress({ value, max = 100, tone = 'sage', height = 6 }: { value: number; max?: number; tone?: string; height?: number }) {
  const pct = Math.min(100, Math.round((value / Math.max(max, 1)) * 100));
  const colors: Record<string, string> = {
    sage: 'bg-sage-500', ok: 'bg-signal-ok', warn: 'bg-signal-warn', bad: 'bg-signal-bad',
  };
  return (
    <div className="w-full rounded-full bg-paper-deep overflow-hidden" style={{ height }}>
      <div className={`${colors[tone] || colors.sage} h-full rounded-full transition-all duration-500`} style={{ width: `${pct}%` }} />
    </div>
  );
}

export function Field({ label, hint, children, required }: any) {
  return (
    <label className="block">
      <div className="flex items-baseline justify-between mb-1.5">
        <span className="text-[13px] font-semibold text-ink-soft">
          {label}{required && <span className="text-signal-bad ml-0.5">*</span>}
        </span>
        {hint && <span className="text-[11px] text-ink-faint">{hint}</span>}
      </div>
      {children}
    </label>
  );
}

export const inputCls =
  'w-full px-3 py-2.5 text-sm bg-white border border-line rounded-xl text-ink placeholder:text-ink-faint transition-colors focus:border-sage-400';

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${inputCls} ${props.className || ''}`} />;
}
export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={`${inputCls} resize-y ${props.className || ''}`} />;
}
export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={`${inputCls} cursor-pointer ${props.className || ''}`} />;
}

export function Empty({ icon, title, body, action }: any) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-16 px-6">
      <div className="w-12 h-12 rounded-2xl bg-paper-deep grid place-items-center text-ink-faint mb-4">{icon}</div>
      <h3 className="text-[15px] font-bold text-ink mb-1.5">{title}</h3>
      <p className="text-[13px] text-ink-muted max-w-sm leading-relaxed mb-4">{body}</p>
      {action}
    </div>
  );
}

export function Modal({ open, onClose, title, subtitle, children, wide = false }: any) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center p-4 sm:p-8 overflow-y-auto">
      <div className="fixed inset-0 bg-ink/25 backdrop-blur-[2px]" onClick={onClose} />
      <div className={`relative bg-white rounded-2xl shadow-lift w-full ${wide ? 'max-w-4xl' : 'max-w-lg'} my-4 animate-rise`}>
        <div className="flex items-start justify-between gap-4 px-6 py-5 border-b border-line">
          <div>
            <h2 className="text-lg font-bold text-ink tracking-[-0.01em]">{title}</h2>
            {subtitle && <p className="text-[13px] text-ink-muted mt-0.5">{subtitle}</p>}
          </div>
          <button onClick={onClose} className="p-1.5 -mr-1.5 rounded-lg text-ink-faint hover:bg-paper-deep hover:text-ink transition-colors">
            <IcX size={18} />
          </button>
        </div>
        <div className="px-6 py-5">{children}</div>
      </div>
    </div>
  );
}

export function Toast({ message, tone = 'ok', onDone }: { message: string; tone?: string; onDone?: () => void }) {
  React.useEffect(() => {
    const t = setTimeout(() => onDone?.(), 4200);
    return () => clearTimeout(t);
  }, [message, onDone]);
  const tones: Record<string, string> = {
    ok: 'bg-ink text-white', bad: 'bg-signal-bad text-white', warn: 'bg-signal-warn text-white',
  };
  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[60] animate-rise">
      <div className={`${tones[tone] || tones.ok} px-4 py-2.5 rounded-xl shadow-lift text-[13px] font-medium flex items-center gap-2 max-w-md`}>
        {tone === 'ok' ? <IcCheck size={15} /> : <IcAlert size={15} />}
        <span className="line-clamp-2">{message}</span>
      </div>
    </div>
  );
}

export function useToast() {
  const [toast, setToast] = React.useState<{ message: string; tone: string } | null>(null);
  const show = React.useCallback((message: string, tone: string = 'ok') => setToast({ message, tone }), []);
  const node = toast ? <Toast message={toast.message} tone={toast.tone} onDone={() => setToast(null)} /> : null;
  return { show, node };
}

export function Tabs({ tabs, active, onChange }: { tabs: { id: string; label: string; count?: number }[]; active: string; onChange: (id: string) => void }) {
  return (
    <div className="flex items-center gap-1 border-b border-line overflow-x-auto">
      {tabs.map((t) => (
        <button key={t.id} onClick={() => onChange(t.id)}
          className={`relative px-3.5 py-2.5 text-[13px] font-semibold whitespace-nowrap transition-colors ${
            active === t.id ? 'text-ink' : 'text-ink-faint hover:text-ink-soft'}`}>
          {t.label}
          {typeof t.count === 'number' && (
            <span className={`ml-1.5 text-[11px] px-1.5 py-0.5 rounded-full ${active === t.id ? 'bg-sage-100 text-sage-800' : 'bg-paper-deep text-ink-faint'}`}>
              {t.count}
            </span>
          )}
          {active === t.id && <span className="absolute left-2 right-2 -bottom-px h-0.5 bg-sage-600 rounded-full" />}
        </button>
      ))}
    </div>
  );
}

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`bg-paper-deep rounded-lg animate-pulseSoft ${className}`} />;
}
