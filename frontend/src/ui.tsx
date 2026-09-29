import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { pretty } from './api'

// ---- Lifeline design system primitives (dark olive + gold) -------------------------------

export function Card({ title, subtitle, icon, status, children, className = '' }: {
  title?: string; subtitle?: string; icon?: ReactNode; status?: ReactNode; children: ReactNode; className?: string
}) {
  return (
    <section className={`rounded-[var(--radius-card)] border border-line bg-card p-5 shadow-[var(--shadow-card)] sm:p-6 ${className}`}>
      {(title || icon || status) && (
        <div className="mb-5 flex items-start gap-3">
          {icon && (
            <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl border border-line bg-surface text-xl" aria-hidden="true">{icon}</div>
          )}
          <div className="min-w-0 flex-1">
            {title && <h2 className="text-lg font-semibold tracking-tight text-ink">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
          </div>
          {status}
        </div>
      )}
      {children}
    </section>
  )
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end gap-4">
      <div className="min-w-0 flex-1">
        <h1 className="text-3xl font-bold tracking-tight text-ink sm:text-4xl">{title}</h1>
        {subtitle && <p className="mt-1.5 max-w-3xl text-ink-2">{subtitle}</p>}
      </div>
      {actions}
    </div>
  )
}

const STATUS_STYLE: Record<string, string> = {
  CONNECTED: 'border-emerald-400/30 bg-emerald-500/12 text-emerald-300',
  LINKED: 'border-gold/30 bg-gold/10 text-gold',
  NEEDS_RECONNECT: 'border-amber-400/30 bg-amber-500/12 text-amber-300',
  ERROR: 'border-red-400/30 bg-red-500/12 text-red-300',
  DISCONNECTED: 'border-line bg-surface text-muted',
}
const STATUS_ICON: Record<string, string> = { CONNECTED: '●', LINKED: '●', NEEDS_RECONNECT: '!', ERROR: '✕', DISCONNECTED: '○' }

export function StatusBadge({ status }: { status: string }) {
  const label = status === 'DISCONNECTED' ? 'Not connected' : pretty(status)
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-1 text-xs font-semibold ${STATUS_STYLE[status] ?? STATUS_STYLE.DISCONNECTED}`}>
      <span aria-hidden="true" className="text-[10px]">{STATUS_ICON[status] ?? '○'}</span>{label}
    </span>
  )
}

type Tone = 'slate' | 'amber' | 'red' | 'green' | 'violet' | 'sky' | 'gold'
const TONES: Record<Tone, string> = {
  slate: 'border-line bg-surface text-ink-2',
  amber: 'border-amber-400/25 bg-amber-500/12 text-amber-300',
  red: 'border-red-400/25 bg-red-500/12 text-red-300',
  green: 'border-emerald-400/25 bg-emerald-500/12 text-emerald-300',
  violet: 'border-violet-400/25 bg-violet-500/12 text-violet-300',
  sky: 'border-sky-400/25 bg-sky-500/12 text-sky-300',
  gold: 'border-gold/30 bg-gold/10 text-gold',
}
export function Badge({ children, tone = 'slate' }: { children: ReactNode; tone?: Tone }) {
  return <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold ${TONES[tone]}`}>{children}</span>
}

export function OriginBadge({ origin }: { origin: 'REAL' | 'DEMO' }) {
  return origin === 'DEMO' ? <Badge tone="violet">◆ DEMO</Badge> : <Badge tone="slate">● REAL</Badge>
}

const TRUST: Record<string, [string, Tone]> = {
  VERIFIED_SENDER: ['✓ Verified sender', 'green'],
  NEW_BILLER_CONFIRM: ['? New biller — confirm', 'amber'],
  UNVERIFIED: ['• Unverified sender', 'slate'],
  SUSPICIOUS: ['⚠ Suspicious', 'red'],
  NOT_APPLICABLE: ['', 'slate'],
}
export function TrustBadge({ label }: { label: string }) {
  const t = TRUST[label]
  if (!t || !t[0]) return null
  return <Badge tone={t[1]}>{t[0]}</Badge>
}

export function Button({ children, variant = 'primary', ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'danger' | 'ghost' }) {
  const styles = {
    primary: 'bg-gold text-bg font-semibold hover:bg-gold-2 active:translate-y-px shadow-[0_6px_20px_-8px_rgb(255_209_0/0.6)]',
    secondary: 'border border-line-strong bg-surface/60 text-ink hover:border-gold/50 hover:bg-raised active:translate-y-px',
    danger: 'border border-red-400/30 bg-red-500/10 text-red-300 hover:bg-red-500/20 active:translate-y-px',
    ghost: 'text-ink-2 hover:bg-raised hover:text-ink',
  }
  return (
    <button {...props} className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-45 ${styles[variant]} ${props.className ?? ''}`}>
      {children}
    </button>
  )
}

export const inputCls = 'min-h-11 rounded-xl border border-line-strong bg-surface px-3 py-2 text-sm text-ink placeholder:text-muted focus:border-gold/60 focus:outline-none focus:ring-2 focus:ring-gold/30'

export function Notice({ tone = 'info', children }: { tone?: 'info' | 'ok' | 'warn' | 'error'; children: ReactNode }) {
  const t = {
    info: 'border-sky-400/25 bg-sky-500/10 text-sky-200',
    ok: 'border-emerald-400/25 bg-emerald-500/10 text-emerald-200',
    warn: 'border-amber-400/25 bg-amber-500/10 text-amber-200',
    error: 'border-red-400/25 bg-red-500/10 text-red-200',
  }
  return <div role={tone === 'error' ? 'alert' : 'status'} aria-live="polite" className={`rounded-xl border px-3.5 py-2.5 text-sm ${t[tone]}`}>{children}</div>
}

export function CopyField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className="mt-1 flex gap-2">
        <code className="flex-1 overflow-x-auto whitespace-nowrap rounded-xl border border-line bg-bg px-3 py-2.5 text-sm text-gold">{value}</code>
        <Button variant="secondary" onClick={() => navigator.clipboard?.writeText(value)} aria-label={`Copy ${label}`}>Copy</Button>
      </div>
    </div>
  )
}

export function Stat({ label, value, hint, accent = false }: { label: string; value: ReactNode; hint?: ReactNode; accent?: boolean }) {
  return (
    <div className={`rounded-2xl border p-4 ${accent ? 'border-gold/40 bg-gold/10' : 'border-line bg-surface/70'}`}>
      <div className="text-xs font-medium uppercase tracking-wider text-muted">{label}</div>
      <div className={`num mt-1 text-2xl font-bold tracking-tight ${accent ? 'text-gold' : 'text-ink'}`}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted">{hint}</div>}
    </div>
  )
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="rounded-[var(--radius-card)] border border-dashed border-line-strong bg-surface/40 p-8 text-center text-ink-2">{children}</div>
}

export const OUTCOME_TEXT: Record<string, string> = {
  SAVED: 'Added to your bills',
  NEEDS_CONFIRMATION: 'Waiting for your confirmation in Review',
  SUSPICIOUS: 'Flagged as suspicious — not added',
  DROPPED_OTP: 'OTP detected — dropped, nothing stored',
  DROPPED_NOT_BILL: 'Not a bill — ignored',
  DUPLICATE: 'Already received — skipped',
  PAID_DETECTED: 'Matched a bill and marked it paid',
  CHARGE_RECORDED: 'Payment noted',
  FAILED: 'Could not process',
}
export function outcomeTone(o: string): 'ok' | 'warn' | 'error' | 'info' {
  if (o === 'SAVED' || o === 'PAID_DETECTED' || o === 'CHARGE_RECORDED') return 'ok'
  if (o === 'SUSPICIOUS' || o === 'FAILED') return 'error'
  if (o === 'NEEDS_CONFIRMATION') return 'warn'
  return 'info'
}

export function Logo() {
  return (
    <Link to="/overview" className="flex items-center gap-2.5" aria-label="Lifeline home">
      <span className="grid h-9 w-9 place-items-center rounded-xl bg-gold text-bg shadow-[0_6px_18px_-6px_rgb(255_209_0/0.7)]">
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M3 12h4l2.5-6 4 12 2.5-6H21" />
        </svg>
      </span>
      <span className="text-lg font-bold tracking-tight text-ink">Lifeline</span>
    </Link>
  )
}

