// Thin fetch wrapper. IMPLEMENTATION DECISION: JWT in localStorage for demo
// simplicity (XSS trade-off noted in the spec; production = httpOnly cookie).
const TOKEN_KEY = 'lifeline_token'

export const auth = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
}

export class ApiError extends Error {
  status: number
  code: string
  details: Record<string, unknown>
  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

export async function api<T = unknown>(path: string, opts: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers = new Headers(opts.headers)
  const token = auth.get()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  let body = opts.body
  if (opts.json !== undefined) {
    headers.set('Content-Type', 'application/json')
    body = JSON.stringify(opts.json)
  }
  const res = await fetch(`/api${path}`, { ...opts, headers, body })
  const data = res.headers.get('content-type')?.includes('json') ? await res.json() : null
  if (!res.ok) {
    if (res.status === 401 && token && !path.startsWith('/ingest/sms')) {
      auth.clear()
      window.location.href = '/login'
    }
    const e = data?.error ?? {}
    throw new ApiError(res.status, e.code ?? 'ERROR', e.message ?? `Request failed (${res.status})`, e.details ?? {})
  }
  return data as T
}

// --- types -------------------------------------------------------------------
export interface User {
  id: string
  email: string
  name: string | null
  phone_e164: string | null
  allow_cloud_image_processing: boolean
  whatsapp_last_inbound_at: string | null
}

export interface GmailSource {
  kind: 'GMAIL'
  mode: 'live' | 'mock'
  status: string
  gmail_address: string | null
  last_sync_at: string | null
  last_error: string | null
}
export interface SmsSource {
  kind: 'SMS'
  status: string
  webhook_url: string
  has_token: boolean
  last_received_at: string | null
  checklist: string[]
  caveat: string
}
export interface WhatsAppSource {
  kind: 'WHATSAPP'
  mode: 'live' | 'mock'
  status: string
  phone_e164: string | null
  sandbox_number: string
  sandbox_join_code: string
  window_open: boolean
  last_inbound_at: string | null
  webhook_url: string
  instructions: string[]
}
export type Source = GmailSource | SmsSource | WhatsAppSource

export interface Obligation {
  id: string
  origin: 'REAL' | 'DEMO'
  type: string
  biller_raw: string | null
  biller_norm: string | null
  amount: string | null
  due_date: string
  status: string
  source_kinds: string[]
  trust_label: string
  confidence: number
  extractors_agreed: boolean
  is_recurring: boolean
  next_expected_date: string | null
  price_changed: boolean
  paid_via: string | null
}

export interface DraftFields {
  biller: string | null
  type: string | null
  amount: string | null
  due_date: string | null
  vehicle_ref: string | null
  message_kind: string | null
}
export interface Confirmation {
  id: string
  origin: 'REAL' | 'DEMO'
  source_kind: string
  reason: string
  created_at: string
  draft: {
    fields: DraftFields
    mismatches?: string[]
    candidates?: { llm?: Record<string, unknown> | null; rules?: Record<string, unknown>; llm_failure?: string }
    trust?: { score: number; label: string; reasons: string[] } | null
    note?: string
  }
}
export interface Flagged {
  id: string
  origin: 'REAL' | 'DEMO'
  source_kind: string
  sender: string | null
  claimed_biller: string | null
  claimed_amount: string | null
  reasons: string[]
  risk_score: number
  created_at: string
}
export interface IngestEvent {
  id: string
  source_kind: string
  received_at: string
  outcome: string
  reason: string | null
}
export interface PipelineResult {
  outcome: string
  summary?: string
  reason?: string
}

// --- formatting ----------------------------------------------------------------
const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 })
export const money = (v: string | number | null | undefined) => (v == null || v === '' ? '—' : inr.format(Number(v)))
export const day = (iso: string | null | undefined) =>
  iso ? new Date(iso.length === 10 ? iso + 'T00:00:00' : iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : '—'
export const when = (iso: string | null | undefined) =>
  iso ? new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z').toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : 'never'
export const pretty = (s: string | null | undefined) => (s ? s.replace(/_/g, ' ').toLowerCase().replace(/^\w/, (c) => c.toUpperCase()) : '')
