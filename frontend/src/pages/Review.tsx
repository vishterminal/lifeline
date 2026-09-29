import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError, day, money, pretty, when, type Confirmation, type Flagged } from '../api'
import { Badge, Button, inputCls, Notice, OriginBadge, TrustBadge } from '../ui'

const REASON_TEXT: Record<string, string> = {
  EXTRACTION_MISMATCH: "Our two readers disagreed. We pre-filled the AI reader's value — tap the other one if that's the right one.",
  LOW_CONFIDENCE: "We weren't sure we read this correctly.",
  NEW_BILLER: 'First bill from this biller — is it genuine?',
  MEDIUM_TRUST: "We couldn't verify the sender.",
  MISSING_FIELDS: 'Some details are missing — please fill them in.',
  RECURRING_CANDIDATE: 'Looks like a subscription — confirm the next renewal.',
  MANUAL_ENTRY: 'You typed this in — check the details and confirm.',
}
const TYPES = ['OTHER', 'ELECTRICITY', 'WATER', 'GAS', 'PHONE_INTERNET', 'INSURANCE_VEHICLE', 'INSURANCE_OTHER', 'PUC',
  'DRIVING_LICENCE', 'VEHICLE_OTHER', 'SUBSCRIPTION', 'LOAN_EMI', 'APPOINTMENT', 'DOCUMENT_OTHER']

function ConfirmationCard({ c }: { c: Confirmation }) {
  const qc = useQueryClient()
  const f = c.draft.fields
  const mismatches = c.draft.mismatches ?? []
  const llm = c.draft.candidates?.llm as Record<string, string> | null | undefined
  const rules = c.draft.candidates?.rules as Record<string, string> | undefined
  const [form, setForm] = useState({
    biller: f.biller ?? '', type: f.type ?? 'OTHER',
    // Pre-filled from what was detected (the AI reader's value when the two readers disagree);
    // the other reader's value is one tap away and nothing is saved until you press Confirm.
    amount: f.amount ?? '',
    due_date: f.due_date ?? '',
  })
  const [err, setErr] = useState<string | null>(null)
  const resolve = useMutation({
    mutationFn: (action: 'confirm' | 'reject') => {
      const fields: Record<string, unknown> = {}
      if (action === 'confirm') {
        if (form.biller !== (f.biller ?? '') || mismatches.includes('biller_norm')) fields.biller = form.biller
        if (form.type !== f.type) fields.type = form.type
        if (form.amount !== (f.amount ?? '') || mismatches.includes('amount')) fields.amount = form.amount || null
        if (form.due_date !== (f.due_date ?? '') || mismatches.includes('due_date')) fields.due_date = form.due_date || null
      }
      return api(`/confirmations/${c.id}/resolve`, { method: 'POST', json: action === 'confirm' ? { action, fields } : { action } })
    },
    onSuccess: () => ['confirmations', 'obligations', 'bills', 'sms-status', 'flagged'].forEach((k) => qc.invalidateQueries({ queryKey: [k] })),
    onError: (e) => setErr(e instanceof ApiError ? e.message : 'Failed'),
  })

  const pick = (key: 'amount' | 'due_date', v: string | undefined) => v && setForm({ ...form, [key]: v })
  const input = 'w-full ' + inputCls

  return (
    <article className="glass glass-hover rounded-[var(--radius-card)] !border-amber-400/25 p-5">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="amber">{pretty(c.reason)}</Badge>
        <OriginBadge origin={c.origin} />
        {(c.draft.sources ?? [c.source_kind]).map((k) => <Badge key={k}>via {pretty(k)}</Badge>)}
        {(c.draft.sources?.length ?? 0) > 1 && <Badge tone="sky">Same bill from {c.draft.sources!.length} channels — shown once</Badge>}
        {c.draft.trust && <TrustBadge label={c.draft.trust.label} />}
        <span className="ml-auto text-xs text-muted">{when(c.created_at)}</span>
      </div>
      <p className="mt-2 text-sm text-ink-2">{REASON_TEXT[c.reason] ?? 'Please check these details.'}</p>

      {mismatches.length > 0 && llm && rules && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-muted"><th className="py-1">Field</th><th>AI reader</th><th>Rule reader</th></tr></thead>
            <tbody>
              {mismatches.map((m) => {
                const key = m === 'biller_norm' ? 'biller' : m
                const fmt = (v: string) => (m === 'amount' ? money(v) : m === 'due_date' ? day(v) : v)
                return (
                  <tr key={m} className="border-t border-line">
                    <td className="py-2 font-medium">{pretty(key)}</td>
                    {[llm[key], rules[key]].map((v, i) => (
                      <td key={i}>
                        {(m === 'amount' || m === 'due_date') ? (
                          <button className="rounded-lg border border-line px-3 py-1.5 hover:bg-raised" onClick={() => pick(m, v)}>
                            {fmt(v)} <span className="text-xs text-muted">use</span>
                          </button>
                        ) : fmt(v)}
                      </td>
                    ))}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {c.draft.trust && c.draft.trust.reasons.length > 0 && (
        <ul className="mt-3 list-disc pl-5 text-xs text-ink-2">{c.draft.trust.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
      )}

      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 [&>*]:min-w-0">
        <label><span className="text-xs font-medium text-muted">Biller</span>
          <input className={input} value={form.biller} onChange={(e) => setForm({ ...form, biller: e.target.value })} /></label>
        <label><span className="text-xs font-medium text-muted">Type</span>
          <select className={input} value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
            {TYPES.map((t) => <option key={t} value={t}>{pretty(t)}</option>)}
          </select></label>
        <label><span className="text-xs font-medium text-muted">Amount ₹ {mismatches.includes('amount') && <b className="text-amber-300">(choose)</b>}</span>
          <input className={input} inputMode="decimal" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} /></label>
        <label><span className="text-xs font-medium text-muted">{f.message_kind === 'RECEIPT' || f.message_kind === 'PAYMENT_CONFIRMATION' ? 'Paid on' : 'Due date'} {mismatches.includes('due_date') && <b className="text-amber-300">(choose)</b>}</span>
          <input className={input} type="date" value={form.due_date} onChange={(e) => setForm({ ...form, due_date: e.target.value })} /></label>
      </div>
      {err && <div className="mt-3"><Notice tone="error">{err}</Notice></div>}
      <div className="mt-4 flex flex-wrap gap-2">
        <Button onClick={() => resolve.mutate('confirm')} disabled={resolve.isPending}>Confirm</Button>
        <Button variant="secondary" onClick={() => resolve.mutate('reject')} disabled={resolve.isPending}>Not a bill / reject</Button>
      </div>
    </article>
  )
}

function FlaggedCard({ item }: { item: Flagged }) {
  const qc = useQueryClient()
  const dismiss = useMutation({
    mutationFn: () => api(`/flagged/${item.id}/dismiss`, { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['flagged'] }),
  })
  return (
    <article className="glass glass-hover rounded-[var(--radius-card)] !border-red-400/25 p-5">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="red">⚠ Suspicious — don't click its links</Badge>
        <OriginBadge origin={item.origin} />
        <Badge>via {pretty(item.source_kind)}</Badge>
        <span className="ml-auto text-xs text-muted">Risk {item.risk_score}/100</span>
      </div>
      <p className="mt-2 text-sm">
        Claims to be <b>{item.claimed_biller ?? 'unknown'}</b> asking for <b className="num">{money(item.claimed_amount)}</b>
        {item.sender && <> from <code className="rounded bg-raised px-1">{item.sender}</code></>}. It was <b>not</b> added to your bills.
      </p>
      <ul className="mt-2 list-disc pl-5 text-sm text-ink-2">{item.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
      <Button className="mt-3" variant="secondary" onClick={() => dismiss.mutate()}>Dismiss</Button>
    </article>
  )
}

export default function Review() {
  const [tab, setTab] = useState<'confirm' | 'suspicious'>('confirm')
  const confs = useQuery({ queryKey: ['confirmations'], queryFn: () => api<Confirmation[]>('/confirmations'), refetchInterval: 30_000 })
  // Demo items first, then your real ones.
  const ordered = [...(confs.data ?? [])].sort((a, b) => (a.origin === b.origin ? 0 : a.origin === 'DEMO' ? -1 : 1))
  const flagged = useQuery({ queryKey: ['flagged'], queryFn: () => api<Flagged[]>('/flagged'), refetchInterval: 30_000 })
  const tabCls = (on: boolean) => `min-h-11 rounded-full px-5 py-2 text-sm font-medium transition ${on ? 'bg-gold text-bg font-semibold shadow-[0_6px_18px_-8px_rgb(255_209_0/0.8)]' : 'glass text-ink-2 hover:text-ink'}`
  const active = tab === 'confirm' ? confs : flagged

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Review</h1>
        <p className="mt-1.5 text-ink-2">Anything we weren't sure about waits here — nothing uncertain is added silently.</p>
      </div>
      <div className="flex gap-2" role="tablist">
        <button role="tab" aria-selected={tab === 'confirm'} className={tabCls(tab === 'confirm')} onClick={() => setTab('confirm')}>
          Needs confirmation ({confs.data?.length ?? 0})
        </button>
        <button role="tab" aria-selected={tab === 'suspicious'} className={tabCls(tab === 'suspicious')} onClick={() => setTab('suspicious')}>
          Suspicious ({flagged.data?.length ?? 0})
        </button>
      </div>
      {active.isLoading && <p className="text-muted">Loading…</p>}
      {active.isError && <Notice tone="error">Couldn't load. <button className="underline" onClick={() => active.refetch()}>Retry</button></Notice>}
      {tab === 'confirm' && confs.data?.length === 0 && (
        <div className="glass rounded-[var(--radius-card)] p-8 text-center text-ink-2">
          All clear. New items appear here as they arrive. <Link to="/connect" className="font-semibold underline">Connect a source</Link>
        </div>
      )}
      {tab === 'suspicious' && flagged.data?.length === 0 && (
        <div className="glass rounded-[var(--radius-card)] p-8 text-center text-ink-2">No suspicious messages.</div>
      )}
      <div className="space-y-4">
        {tab === 'confirm' && ordered.map((c, i) => (
          <div key={c.id}>
            {c.origin === 'REAL' && (i === 0 || ordered[i - 1].origin !== 'REAL') && ordered.some((x) => x.origin === 'DEMO') && (
              <h2 className="mb-3 mt-8 text-sm font-semibold uppercase tracking-wider text-muted">Your real items</h2>
            )}
            <ConfirmationCard c={c} />
          </div>
        ))}
        {tab === 'suspicious' && flagged.data?.map((f) => <FlaggedCard key={f.id} item={f} />)}
      </div>
    </div>
  )
}
