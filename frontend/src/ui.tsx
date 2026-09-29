import type { ReactNode } from 'react'
import { pretty } from './api'

export function Card({ title, subtitle, icon, status, children }: {
  title: string; subtitle?: string; icon?: ReactNode; status?: ReactNode; children: ReactNode
}) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-start gap-3">
        {icon && <div className="mt-0.5 text-2xl" aria-hidden="true">{icon}</div>}
        <div className="flex-1">
          <h2 className="text-lg font-semibold">{title}</h2>
          {subtitle && <p className="text-sm text-slate-600">{subtitle}</p>}
        </div>
        {status}
      </div>
      {children}
    </section>
  )
}

const STATUS_STYLE: Record<string, string> = {
  CONNECTED: 'bg-emerald-100 text-emerald-800',
  LINKED: 'bg-sky-100 text-sky-800',
  NEEDS_RECONNECT: 'bg-amber-100 text-amber-800',
  ERROR: 'bg-red-100 text-red-800',
  DISCONNECTED: 'bg-slate-100 text-slate-600',
}
const STATUS_ICON: Record<string, string> = { CONNECTED: '✓', LINKED: '•', NEEDS_RECONNECT: '!', ERROR: '✕', DISCONNECTED: '○' }

export function StatusBadge({ status }: { status: string }) {
  const label = status === 'DISCONNECTED' ? 'Not connected' : pretty(status)
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ${STATUS_STYLE[status] ?? STATUS_STYLE.DISCONNECTED}`}>
      <span aria-hidden="true">{STATUS_ICON[status] ?? '○'}</span>{label}
    </span>
  )
}

export function Badge({ children, tone = 'slate' }: { children: ReactNode; tone?: 'slate' | 'amber' | 'red' | 'green' | 'violet' | 'sky' }) {
  const tones = {
    slate: 'bg-slate-100 text-slate-700', amber: 'bg-amber-100 text-amber-800', red: 'bg-red-100 text-red-800',
    green: 'bg-emerald-100 text-emerald-800', violet: 'bg-violet-100 text-violet-800', sky: 'bg-sky-100 text-sky-800',
  }
  return <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ${tones[tone]}`}>{children}</span>
}

export function OriginBadge({ origin }: { origin: 'REAL' | 'DEMO' }) {
  return origin === 'DEMO' ? <Badge tone="violet">◆ DEMO</Badge> : <Badge tone="slate">● REAL</Badge>
}

const TRUST: Record<string, [string, 'green' | 'amber' | 'red' | 'slate' | 'sky']> = {
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
    primary: 'bg-slate-900 text-white hover:bg-slate-800',
    secondary: 'border border-slate-300 bg-white hover:bg-slate-50',
    danger: 'border border-red-200 bg-white text-red-700 hover:bg-red-50',
    ghost: 'text-slate-600 hover:bg-slate-100',
  }
  return (
    <button {...props} className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium disabled:opacity-50 ${styles[variant]} ${props.className ?? ''}`}>
      {children}
    </button>
  )
}

export function Notice({ tone = 'info', children }: { tone?: 'info' | 'ok' | 'warn' | 'error'; children: ReactNode }) {
  const t = { info: 'bg-sky-50 text-sky-900', ok: 'bg-emerald-50 text-emerald-900', warn: 'bg-amber-50 text-amber-900', error: 'bg-red-50 text-red-800' }
  return <div role={tone === 'error' ? 'alert' : 'status'} aria-live="polite" className={`rounded-lg px-3 py-2 text-sm ${t[tone]}`}>{children}</div>
}

export function CopyField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <div className="mt-1 flex gap-2">
        <code className="flex-1 overflow-x-auto whitespace-nowrap rounded-lg bg-slate-100 px-3 py-2 text-sm">{value}</code>
        <Button variant="secondary" onClick={() => navigator.clipboard?.writeText(value)} aria-label={`Copy ${label}`}>Copy</Button>
      </div>
    </div>
  )
}

export const OUTCOME_TEXT: Record<string, string> = {
  SAVED: 'Added to your bills',
  NEEDS_CONFIRMATION: 'Waiting for your confirmation in Review',
  SUSPICIOUS: 'Flagged as suspicious — not added',
  DROPPED_OTP: 'OTP detected — dropped, nothing stored',
  DROPPED_NOT_BILL: "Not a bill — ignored",
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
