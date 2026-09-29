import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'
import { api, ApiError, day, money, pretty, type BillShock, type RankedBill, type SplitState, type WhatIf } from '../api'
import { Badge, Button, EmptyState, inputCls, Notice, OriginBadge, PageHeader, TrustBadge } from '../ui'

const ICON: Record<string, string> = {
  ELECTRICITY: '⚡', WATER: '💧', GAS: '🔥', PHONE_INTERNET: '📶', INSURANCE_VEHICLE: '🏍️', INSURANCE_OTHER: '🛡️',
  PUC: '🚘', DRIVING_LICENCE: '🪪', SUBSCRIPTION: '🔁', LOAN_EMI: '🏦', APPOINTMENT: '📅',
}
const OPEN = new Set(['OPEN', 'OVERDUE'])

function daysLeft(iso: string) {
  const d = Math.round((new Date(iso + 'T00:00:00').getTime() - new Date(new Date().toDateString()).getTime()) / 86400000)
  if (d === 0) return 'due today'
  if (d === 1) return 'due tomorrow'
  return d < 0 ? `${-d} days overdue` : `in ${d} days`
}

function ShockBox({ shock }: { shock: BillShock }) {
  const max = Math.max(...shock.history.map((h) => Number(h.amount)))
  return (
    <div className="mt-2 rounded-lg border border-red-400/25 bg-red-500/10 px-2.5 py-2 text-sm text-red-200">
      <div>⚠ {shock.pct}% higher than your usual {money(shock.usual)} (+{money(shock.extra)}), based on your last {shock.based_on} bill{shock.based_on === 1 ? '' : 's'}</div>
      <div className="mt-2 flex h-12 items-end gap-1.5" aria-label="Your recent bills from this biller">
        {shock.history.map((h, i) => {
          const last = i === shock.history.length - 1
          return (
            <div key={h.date + i} className="flex flex-col items-center gap-0.5" title={`${day(h.date)}: ${money(h.amount)}`}>
              <div className={`w-6 rounded-t ${last ? 'bg-red-400' : 'bg-ink-2/40'}`} style={{ height: `${Math.max(8, (Number(h.amount) / max) * 36)}px` }} />
              <span className="num text-[10px] text-muted">{money(h.amount)}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function RiskBadge({ tier }: { tier: 'HIGH' | 'MEDIUM' | 'LOW' }) {
  const t = { HIGH: ['▲ High risk', 'red'], MEDIUM: ['● Medium risk', 'amber'], LOW: ['▼ Low risk', 'green'] } as const
  return <Badge tone={t[tier][1]}>{t[tier][0]}</Badge>
}

export function VerifiedBadge({ label }: { label: string }) {
  if (label === 'VERIFIED') return <Badge tone="green">✓ Verified</Badge>
  if (label === 'UNKNOWN') return <Badge>? Unknown</Badge>
  return <Badge tone="gold">≈ Estimated</Badge>
}

function PayDialog({ bill, onClose }: { bill: RankedBill; onClose: () => void }) {
  const qc = useQueryClient()
  const [done, setDone] = useState(false)
  const pay = useMutation({
    mutationFn: () => api(`/obligations/${bill.id}/pay-mock`, { method: 'POST' }),
    onSuccess: () => { setDone(true); ['bills', 'obligations'].forEach((k) => qc.invalidateQueries({ queryKey: [k] })) },
  })
  // Portal to <body>: a transformed ancestor (card hover lift) would otherwise trap position:fixed.
  return createPortal(
    <div className="fixed inset-0 z-40 grid place-items-center bg-black/60 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="pay-title">
      <div className="glass w-full max-w-md rounded-[var(--radius-card)] p-6">
        <div className="mb-4 rounded-xl border border-gold/40 bg-gold/10 px-3 py-2 text-sm font-semibold text-gold">⚠ Simulated — no real money moves</div>
        <h2 id="pay-title" className="text-xl font-semibold">{done ? 'Payment simulated' : `Pay ${bill.biller_raw ?? 'bill'}`}</h2>
        <div className="num mt-2 text-3xl font-bold text-gold">{money(bill.amount)}</div>
        <p className="mt-2 text-sm text-ink-2">
          {done ? 'Marked as paid. Reminders for this bill would stop here.'
            : 'Lifeline never uses payment links from the original message. In production this hands off to a licensed payment partner.'}
        </p>
        <div className="mt-5 flex gap-2">
          {!done && <Button onClick={() => pay.mutate()} disabled={pay.isPending}>{pay.isPending ? 'Processing…' : 'Pay (simulated)'}</Button>}
          <Button variant="secondary" onClick={onClose}>{done ? 'Done' : 'Cancel'}</Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

function PenaltyFighter({ bill }: { bill: RankedBill }) {
  const [draft, setDraft] = useState<{ draft_id: string; text: string; likelihood: string } | null>(null)
  const [copied, setCopied] = useState(false)
  const [outcome, setOutcome] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const make = useMutation({
    mutationFn: () => api<{ draft_id: string; text: string; likelihood: string }>(`/obligations/${bill.id}/waiver-draft`, { method: 'POST' }),
    onSuccess: (r) => { setDraft(r); setErr(null) },
    onError: (e) => setErr(e instanceof ApiError ? e.message : 'Failed'),
  })
  const record = useMutation({
    mutationFn: (o: 'GRANTED' | 'DENIED') => api(`/waiver-drafts/${draft!.draft_id}`, { method: 'PATCH', json: { outcome: o } }),
    onSuccess: (_r, o) => setOutcome(o),
  })
  return (
    <div className="glass-inner rounded-2xl p-4 md:col-span-2">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex-1"><b className="text-gold">✍️ Penalty Fighter</b><div className="text-sm text-muted">This bill is overdue. Draft a polite request to waive the late fee — built only from facts, you review and send it.</div></div>
        <Button onClick={() => make.mutate()} disabled={make.isPending}>{make.isPending ? 'Drafting…' : draft ? 'Redraft' : 'Draft waiver request'}</Button>
      </div>
      {err && <div className="mt-3"><Notice tone="error">{err}</Notice></div>}
      {draft && (
        <div className="mt-3 space-y-3">
          <textarea readOnly value={draft.text} aria-label="Waiver request draft" rows={12} className="w-full rounded-xl border border-line-strong bg-bg/60 p-3 font-mono text-xs text-ink" />
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="secondary" onClick={() => { navigator.clipboard?.writeText(draft.text); setCopied(true) }}>{copied ? '✓ Copied' : 'Copy text'}</Button>
            <span className="text-xs text-muted">Chance of waiver: {draft.likelihood}</span>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-ink-2">After you send it — what happened?</span>
            <Button variant="secondary" onClick={() => record.mutate('GRANTED')} disabled={record.isPending}>Waived 🎉</Button>
            <Button variant="ghost" onClick={() => record.mutate('DENIED')} disabled={record.isPending}>Refused</Button>
            {outcome && <Badge tone={outcome === 'GRANTED' ? 'green' : 'slate'}>Recorded: {outcome.toLowerCase()}</Badge>}
          </div>
        </div>
      )}
    </div>
  )
}

function SplitPanel({ bill }: { bill: RankedBill }) {
  const qc = useQueryClient()
  const split = useQuery({ queryKey: ['split', bill.id], queryFn: () => api<SplitState>(`/obligations/${bill.id}/splits`) })
  const [people, setPeople] = useState([{ name: '', phone_e164: '' }])
  const [editing, setEditing] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const refresh = () => qc.invalidateQueries({ queryKey: ['split', bill.id] })
  const save = useMutation({
    mutationFn: () => api<SplitState>(`/obligations/${bill.id}/splits`, { method: 'POST', json: {
      people: people.filter((p) => p.name.trim()).map((p) => ({ name: p.name.trim(), phone_e164: p.phone_e164.trim() || null })), include_me: true } }),
    onSuccess: () => { setEditing(false); setMsg(null); refresh() },
    onError: (e) => setMsg(e instanceof ApiError ? e.message : 'Failed'),
  })
  const paid = useMutation({ mutationFn: (id: string) => api(`/splits/${id}/paid`, { method: 'POST' }), onSuccess: refresh })
  const remind = useMutation({
    mutationFn: (id: string) => api<{ status: string; message: string }>(`/splits/${id}/remind`, { method: 'POST' }),
    onSuccess: (r) => { setMsg(`${r.status === 'SENT' ? 'Sent' : 'Simulated (demo)'}: “${r.message}”`); refresh() },
  })
  const s = split.data
  if (bill.amount == null) return null
  return (
    <div className="glass-inner rounded-2xl p-4 md:col-span-2">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex-1"><b className="text-gold">👥 Split this bill</b>
          <div className="text-sm text-muted">{s && s.shares.length ? `Your share ${money(s.my_share)} · others owe ${money(s.others_owe)}` : 'Share it equally with flatmates or family and remind them.'}</div></div>
        {!editing && <Button variant="secondary" onClick={() => setEditing(true)}>{s && s.shares.length ? 'Change split' : 'Split'}</Button>}
      </div>
      {editing && (
        <form className="mt-3 space-y-2" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
          {people.map((p, i) => (
            <div key={i} className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <input className={inputCls} placeholder="Name" aria-label={`Person ${i + 1} name`} value={p.name}
                onChange={(e) => setPeople(people.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
              <input className={inputCls} placeholder="+91… (optional)" aria-label={`Person ${i + 1} phone`} value={p.phone_e164}
                onChange={(e) => setPeople(people.map((x, j) => (j === i ? { ...x, phone_e164: e.target.value } : x)))} />
            </div>
          ))}
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="ghost" onClick={() => setPeople([...people, { name: '', phone_e164: '' }])}>+ Add person</Button>
            <Button type="submit" disabled={save.isPending || !people.some((p) => p.name.trim())}>Split equally</Button>
            <Button type="button" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
          </div>
        </form>
      )}
      {s && s.shares.length > 0 && !editing && (
        <ul className="mt-3 divide-y divide-white/[0.07]">
          {s.shares.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
              <span className="flex-1">{r.name} <span className="num text-muted">owes {money(r.share_amount)}</span></span>
              {r.paid ? <Badge tone="green">✓ Paid you</Badge> : <>
                <Button variant="secondary" onClick={() => remind.mutate(r.id)} disabled={remind.isPending}>Remind</Button>
                <Button variant="ghost" onClick={() => paid.mutate(r.id)} disabled={paid.isPending}>Mark paid</Button>
              </>}
            </li>
          ))}
        </ul>
      )}
      {msg && <div className="mt-2"><Notice tone="info">{msg}</Notice></div>}
    </div>
  )
}

function BillDetail({ bill }: { bill: RankedBill }) {
  const qc = useQueryClient()
  const c = bill.consequence
  const [paying, setPaying] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const wi = useQuery({ queryKey: ['whatif', bill.id], queryFn: () => api<WhatIf>(`/obligations/${bill.id}/whatif`), enabled: false })
  const act = useMutation({
    mutationFn: (a: 'mark-paid' | 'dismiss' | 'snooze-15' | 'snooze-30') => a.startsWith('snooze')
      ? api(`/obligations/${bill.id}/snooze`, { method: 'POST', json: { minutes: Number(a.split('-')[1]) } })
      : api(`/obligations/${bill.id}/${a}`, { method: 'POST' }),
    onSuccess: () => ['bills', 'obligations'].forEach((k) => qc.invalidateQueries({ queryKey: [k] })),
    onError: (e) => setErr(e instanceof ApiError ? e.message : 'Failed'),
  })
  const open = OPEN.has(bill.status)
  return (
    <div className="mt-4 grid grid-cols-1 gap-4 border-t border-line pt-4 md:grid-cols-2 [&>*]:min-w-0">
      <div>
        <h3 className="text-sm font-semibold uppercase tracking-wider text-muted">₹ consequence if missed</h3>
        <dl className="mt-2 space-y-1.5 text-sm">
          <div className="flex justify-between"><dt className="text-ink-2">Direct</dt><dd className="num">{c.direct != null ? money(c.direct) : 'Unknown'}</dd></div>
          <div className="flex justify-between"><dt className="text-ink-2">Knock-on (chain)</dt><dd className="num">{money(c.downstream)}</dd></div>
          <div className="flex justify-between border-t border-line pt-1.5 font-semibold"><dt>Total at risk</dt><dd className="num text-gold">{money(c.total)}</dd></div>
        </dl>
        <ul className="mt-3 space-y-1 text-xs text-muted">{c.explanation.map((e) => <li key={e}>• {e}</li>)}</ul>
        {c.sources.length > 0 && <p className="mt-2 text-xs text-muted">Source: {c.sources.join(' · ')}</p>}
      </div>
      <div>
        <h3 className="text-sm font-semibold uppercase tracking-wider text-muted">Chain</h3>
        {c.upstream.length + c.downstream_links.length === 0 ? <p className="mt-2 text-sm text-muted">No linked obligations.</p> : (
          <ol className="mt-2 space-y-2 text-sm">
            {c.upstream.map((l, i) => (
              <li key={`u${i}`} className="rounded-xl border border-amber-400/25 bg-amber-500/10 p-2.5">
                <b className="text-amber-200">Needs first:</b> {l.label}{l.due_date && <span className="text-muted"> · due {day(l.due_date)}</span>}
                <div className="text-xs text-ink-2">{l.explanation}</div>
              </li>
            ))}
            <li className="rounded-xl border border-gold/40 bg-gold/10 p-2.5 font-semibold text-gold">● {bill.biller_raw ?? pretty(bill.type)}</li>
            {c.downstream_links.map((l, i) => (
              <li key={`d${i}`} className="rounded-xl border border-red-400/25 bg-red-500/10 p-2.5">
                <b className="text-red-200">{l.relation === 'BLOCKS_RENEWAL' ? '→ Blocks' : '→ Affects'}:</b> {l.label}
                {l.cost && <span className="num text-muted"> · ~{money(l.cost)}</span>}
                <div className="text-xs text-ink-2">{l.explanation}</div>
              </li>
            ))}
          </ol>
        )}
      </div>
      <div className="md:col-span-2">
        <Button variant="secondary" onClick={() => wi.refetch()} disabled={wi.isFetching}>{wi.isFetching ? 'Simulating…' : '🔮 What if I skip this?'}</Button>
        {wi.data && (
          <div className="glass-inner mt-3 rounded-2xl p-4">
            <div className="text-sm">If you skip <b>{wi.data.skipped}</b>, it could cost <b className="num text-gold">{money(wi.data.total)}</b> <VerifiedBadge label={wi.data.label} /></div>
            <ol className="mt-2 space-y-1.5 text-sm">
              {wi.data.timeline_effects.map((e, i) => (
                <li key={i} className="flex gap-3"><span className="w-24 shrink-0 text-muted">{day(e.date)}</span><span className="text-ink-2">{e.text}</span></li>
              ))}
            </ol>
          </div>
        )}
      </div>
      {open && (
        <div className="flex flex-wrap gap-2 md:col-span-2">
          <Button onClick={() => setPaying(true)}>Pay now (simulated)</Button>
          <Button variant="secondary" onClick={() => act.mutate('mark-paid')} disabled={act.isPending}>I've paid this</Button>
          <Button variant="secondary" onClick={() => act.mutate('snooze-30')} disabled={act.isPending}>Remind me in 30 min</Button>
          <Button variant="ghost" onClick={() => act.mutate('dismiss')} disabled={act.isPending}>Dismiss</Button>
        </div>
      )}
      {open && <SplitPanel bill={bill} />}
      {(bill.status === 'OVERDUE' || (open && new Date(bill.due_date + 'T00:00:00') < new Date(new Date().toDateString()))) && <PenaltyFighter bill={bill} />}
      {err && <div className="md:col-span-2"><Notice tone="error">{err}</Notice></div>}
      {paying && <PayDialog bill={bill} onClose={() => setPaying(false)} />}
    </div>
  )
}

export default function Bills() {
  const [sort, setSort] = useState<'risk' | 'date'>('risk')
  const [openId, setOpenId] = useState<string | null>(null)
  const bills = useQuery({ queryKey: ['bills', sort], queryFn: () => api<RankedBill[]>(`/bills?sort=${sort}`), refetchInterval: 30_000 })
  const openBills = (bills.data ?? []).filter((b) => OPEN.has(b.status))
  // Sum each bill's own penalty once; knock-on effects are shown per bill (summing totals would double-count chains).
  const atRisk = openBills.reduce((s, b) => s + Number(b.consequence.direct ?? 0), 0)
  const tabCls = (on: boolean) => `min-h-10 rounded-full px-4 text-sm font-medium ${on ? 'bg-gold text-bg' : 'text-ink-2 hover:text-ink'}`

  return (
    <div className="mx-auto max-w-5xl">
      <div>
        <PageHeader title="Bills" subtitle="Ranked by what missing them would really cost you — not just by date."
          actions={
            <div className="flex flex-wrap items-center gap-2">
            <Link to="/subscriptions" className="glass inline-flex min-h-11 items-center rounded-full px-4 text-sm font-medium text-ink-2 hover:text-gold">🔁 Subscriptions</Link>
            <div className="glass flex rounded-full p-1" role="tablist" aria-label="Sort bills">
              <button role="tab" aria-selected={sort === 'risk'} className={tabCls(sort === 'risk')} onClick={() => setSort('risk')}>By ₹ risk</button>
              <button role="tab" aria-selected={sort === 'date'} className={tabCls(sort === 'date')} onClick={() => setSort('date')}>By date</button>
            </div>
            </div>
          } />
        {openBills.length > 0 && (
          <div className="glass mb-4 flex flex-wrap items-center gap-3 rounded-2xl !border-gold/30 px-4 py-3 text-sm">
            <span className="text-ink-2">Penalties at stake across {openBills.length} open bill{openBills.length === 1 ? '' : 's'}:</span>
            <b className="num text-lg text-gold">{money(atRisk)}</b>
            <VerifiedBadge label={openBills.every((b) => b.consequence.label === 'VERIFIED') ? 'VERIFIED' : 'ESTIMATED'} />
          </div>
        )}
        {openBills.filter((b) => b.shock).map((b) => (
          <div key={b.id} className="mb-3"><Notice tone="warn">⚠ <b>Bill shock:</b> {b.biller_raw ?? b.biller_norm} is <b>{money(b.amount)}</b>, {b.shock!.pct}% higher than your usual {money(b.shock!.usual)} (+{money(b.shock!.extra)}). Check the reading or the tariff before you pay.</Notice></div>
        ))}
        {bills.isLoading && <p className="text-muted">Loading…</p>}
        {bills.isError && <Notice tone="error">Couldn't load bills. <button className="underline" onClick={() => bills.refetch()}>Retry</button></Notice>}
        {bills.data?.length === 0 && <EmptyState>Nothing tracked yet — <Link to="/connect" className="font-semibold text-gold underline">connect a source or run the demo</Link>.</EmptyState>}
        <ul className="space-y-3">
          {bills.data?.map((o) => {
            const isOpen = OPEN.has(o.status)
            const expanded = openId === o.id
            return (
              <li key={o.id} className={`glass glass-hover rounded-[var(--radius-card)] p-4 sm:p-5 ${isOpen ? (o.consequence.tier === 'HIGH' ? '!border-red-400/30' : '') : 'opacity-60'}`}>
                <button className="flex w-full items-start gap-3 text-left" onClick={() => setOpenId(expanded ? null : o.id)} aria-expanded={expanded}>
                  <div className="glass-inner grid h-11 w-11 shrink-0 place-items-center rounded-xl text-xl" aria-hidden="true">{ICON[o.type] ?? '📄'}</div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-baseline gap-x-3">
                      <h2 className="font-semibold">{o.biller_raw ?? o.biller_norm ?? 'Bill'}</h2>
                      <span className="text-sm text-muted">{pretty(o.type)}</span>
                    </div>
                    <div className="mt-1 text-sm text-ink-2">
                      {o.status === 'PAID' ? <>Paid{o.paid_via === 'AUTO_DETECTED' ? ' (detected from your payment message)' : o.paid_via === 'MOCK' ? ' (simulated payment)' : ''}</>
                        : o.status === 'DISMISSED' ? 'Dismissed'
                        : <>{o.is_recurring ? 'Renews' : 'Due'} {day(o.due_date)} · <b>{daysLeft(o.due_date)}</b></>}
                    </div>
                    {isOpen && o.chain_hint && <div className="mt-2 rounded-lg border border-amber-400/25 bg-amber-500/10 px-2.5 py-1.5 text-sm text-amber-200">⛓ {o.chain_hint}</div>}
                    {o.shock && <ShockBox shock={o.shock} />}
                    {isOpen && o.autopay && <div className="mt-2 rounded-lg border border-sky-400/25 bg-sky-500/10 px-2.5 py-1.5 text-sm text-sky-200">⚡ AutoPay: this will be charged automatically on {day(o.due_date)}. <Link to="/subscriptions" className="font-semibold underline" onClick={(e) => e.stopPropagation()}>Still using it?</Link></div>}
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {isOpen && <RiskBadge tier={o.consequence.tier} />}
                      <OriginBadge origin={o.origin} />
                      {o.trust_label === 'NEW_BILLER_CONFIRM' ? <Badge tone="green">✓ Confirmed by you</Badge> : <TrustBadge label={o.trust_label} />}
                      {o.is_recurring && <Badge tone="sky">🔁 Recurring</Badge>}
                      {o.price_changed && <Badge tone="amber">Price changed</Badge>}
                      {o.autopay && <Badge tone="sky">⚡ AutoPay</Badge>}
                      {o.shock && <Badge tone="red">⚠ {o.shock.pct}% higher than usual</Badge>}
                      {o.status === 'OVERDUE' && <Badge tone="red">Overdue</Badge>}
                      {o.source_kinds.map((s) => <Badge key={s}>from {pretty(s)}</Badge>)}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="num text-lg font-semibold">{money(o.amount)}</div>
                    {isOpen && (
                      <div className="mt-1 text-xs">
                        <span className="num font-semibold text-gold">{money(o.consequence.total)}</span>
                        <span className="text-muted"> at risk</span>
                        <div className="mt-1"><VerifiedBadge label={o.consequence.label} /></div>
                      </div>
                    )}
                  </div>
                </button>
                {expanded && <BillDetail bill={o} />}
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}
