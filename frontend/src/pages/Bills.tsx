import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, day, money, pretty, when, type IngestEvent, type Obligation } from '../api'
import { Badge, Notice, OriginBadge, OUTCOME_TEXT, TrustBadge } from '../ui'

const ICON: Record<string, string> = {
  ELECTRICITY: '⚡', WATER: '💧', GAS: '🔥', PHONE_INTERNET: '📶', INSURANCE_VEHICLE: '🏍️', INSURANCE_OTHER: '🛡️',
  PUC: '🌫️', DRIVING_LICENCE: '🪪', SUBSCRIPTION: '🔁', LOAN_EMI: '🏦', APPOINTMENT: '📅',
}

function daysLeft(iso: string) {
  const d = Math.round((new Date(iso + 'T00:00:00').getTime() - new Date(new Date().toDateString()).getTime()) / 86400000)
  if (d === 0) return 'due today'
  if (d === 1) return 'due tomorrow'
  return d < 0 ? `${-d} days overdue` : `in ${d} days`
}

export default function Bills() {
  const obls = useQuery({ queryKey: ['obligations'], queryFn: () => api<Obligation[]>('/obligations'), refetchInterval: 30_000 })
  const events = useQuery({ queryKey: ['events'], queryFn: () => api<IngestEvent[]>('/ingest-events?limit=20'), refetchInterval: 30_000 })

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="space-y-4 lg:col-span-2">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Bills found</h1>
          <p className="text-slate-600">Everything collected so far, soonest first. (Ranking by ₹ risk comes next.)</p>
        </div>
        {obls.isLoading && <p className="text-slate-500">Loading…</p>}
        {obls.isError && <Notice tone="error">Couldn't load bills. <button className="underline" onClick={() => obls.refetch()}>Retry</button></Notice>}
        {obls.data?.length === 0 && (
          <div className="rounded-2xl border border-dashed border-slate-300 p-8 text-center text-slate-600">
            Nothing tracked yet — <Link to="/connect" className="font-semibold underline">connect a source or try a demo message</Link>.
          </div>
        )}
        <ul className="space-y-3">
          {obls.data?.map((o) => (
            <li key={o.id} className={`rounded-2xl border bg-white p-4 shadow-sm ${o.status === 'PAID' ? 'border-slate-200 opacity-70' : 'border-slate-200'}`}>
              <div className="flex items-start gap-3">
                <div className="text-2xl" aria-hidden="true">{ICON[o.type] ?? '📄'}</div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-x-3">
                    <h2 className="font-semibold">{o.biller_raw ?? o.biller_norm ?? 'Bill'}</h2>
                    <span className="text-sm text-slate-500">{pretty(o.type)}</span>
                  </div>
                  <div className="mt-1 text-sm text-slate-700">
                    {o.status === 'PAID' ? <>Paid{o.paid_via === 'AUTO_DETECTED' ? ' (detected from your payment message)' : ''}</> :
                      <>{o.is_recurring ? 'Renews' : 'Due'} {day(o.due_date)} · <b>{daysLeft(o.due_date)}</b></>}
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <OriginBadge origin={o.origin} />
                    <TrustBadge label={o.trust_label} />
                    {o.is_recurring && <Badge tone="sky">🔁 Recurring</Badge>}
                    {o.price_changed && <Badge tone="amber">Price changed</Badge>}
                    {o.status === 'OVERDUE' && <Badge tone="red">Overdue</Badge>}
                    {o.source_kinds.map((s) => <Badge key={s}>from {pretty(s)}</Badge>)}
                  </div>
                </div>
                <div className="num text-right text-lg font-semibold">{money(o.amount)}</div>
              </div>
            </li>
          ))}
        </ul>
      </div>
      <aside>
        <h2 className="mb-3 text-lg font-semibold">Recent activity</h2>
        <p className="mb-3 text-xs text-slate-500">What happened to each incoming message. Message text is never stored.</p>
        <ul className="space-y-2">
          {events.data?.map((e) => (
            <li key={e.id} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm">
              <div className="flex justify-between gap-2"><b>{pretty(e.source_kind)}</b><span className="text-xs text-slate-500">{when(e.received_at)}</span></div>
              <div className="text-slate-700">{OUTCOME_TEXT[e.outcome] ?? e.outcome}</div>
            </li>
          ))}
          {events.data?.length === 0 && <li className="text-sm text-slate-500">No messages yet.</li>}
        </ul>
      </aside>
    </div>
  )
}
