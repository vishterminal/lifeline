import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, ApiError, money, when, type ReminderRow } from '../api'
import { Badge, Button, EmptyState, Notice, PageHeader } from '../ui'

const CH: Record<string, [string, 'gold' | 'sky' | 'green' | 'violet']> = {
  IN_APP: ['🔔 In-app', 'gold'], PUSH: ['📲 Push', 'sky'], WHATSAPP: ['💬 WhatsApp', 'green'], FAMILY_WHATSAPP: ['👪 Family alert', 'violet'],
}
const STATUS: Record<string, [string, 'green' | 'slate' | 'amber' | 'red']> = {
  SENT: ['Sent', 'green'], SIMULATED: ['Simulated (demo)', 'slate'], SKIPPED_QUIET_HOURS: ['Held — quiet hours', 'amber'],
  SKIPPED_WINDOW_CLOSED: ['WhatsApp window closed → push', 'amber'], FAILED: ['Failed', 'red'],
}
const TIER: Record<string, 'red' | 'amber' | 'green'> = { HIGH: 'red', MEDIUM: 'amber', LOW: 'green' }

export default function Reminders() {
  const qc = useQueryClient()
  const [msg, setMsg] = useState<{ tone: 'ok' | 'info' | 'error'; text: string } | null>(null)
  const feed = useQuery({ queryKey: ['reminders'], queryFn: () => api<ReminderRow[]>('/reminders?limit=200'), refetchInterval: 30_000 })
  const refresh = () => ['reminders', 'bills', 'obligations'].forEach((k) => qc.invalidateQueries({ queryKey: [k] }))
  const err = (e: unknown) => setMsg({ tone: 'error', text: e instanceof ApiError ? e.message : 'Something went wrong' })
  const tick = useMutation({
    mutationFn: () => api<{ sent: number; simulated: number; skipped: number; family: number }>('/reminders/tick', { method: 'POST' }),
    onSuccess: (r) => { refresh(); setMsg({ tone: r.sent + r.simulated ? 'ok' : 'info', text: r.sent + r.simulated ? `Sent ${r.sent} reminder(s)${r.simulated ? `, ${r.simulated} simulated` : ''}${r.skipped ? `, ${r.skipped} held` : ''}.` : 'Nothing due for a reminder right now.' }) },
    onError: err,
  })
  const sim = useMutation({
    mutationFn: () => api<{ total: { sent: number; simulated: number; skipped: number; family: number } }>('/reminders/simulate', { method: 'POST', json: { days: 7 } }),
    onSuccess: (r) => {
      refresh()
      const n = r.total.sent + r.total.simulated
      setMsg(n ? { tone: 'ok', text: `Next 7 days simulated: ${n} reminders across channels${r.total.family ? `, ${r.total.family} family alert(s)` : ''}.` }
        : { tone: 'info', text: 'Next 7 days simulated: no open bills need a reminder in that window.' })
    },
    onError: err,
  })
  const clear = useMutation({ mutationFn: () => api('/reminders/simulated', { method: 'DELETE' }), onSuccess: () => { refresh(); setMsg(null) } })
  const act = useMutation({
    mutationFn: ([id, a]: [string, string]) => a.startsWith('snooze')
      ? api(`/obligations/${id}/snooze`, { method: 'POST', json: { minutes: Number(a.split(':')[1]) } })
      : api(`/obligations/${id}/${a}`, { method: 'POST' }),
    onSuccess: (_r, [, a]) => { refresh(); setMsg({ tone: 'ok', text: a === 'mark-paid' ? 'Marked paid — reminders stopped.' : a === 'dismiss' ? 'Dismissed — no more reminders.' : `Snoozed ${a.split(':')[1]} minutes.` }) },
    onError: err,
  })

  const rows = feed.data ?? []
  const byBill = new Map<string, ReminderRow>()
  rows.forEach((r) => { if (!byBill.has(r.obligation_id)) byBill.set(r.obligation_id, r) })

  return (
    <div>
      <PageHeader title="Reminders" subtitle="Loudness follows ₹ risk: low-risk bills get a gentle nudge, high-risk ones escalate to WhatsApp and, as a last resort, a family member."
        actions={<div className="flex flex-wrap gap-2">
          <Button onClick={() => tick.mutate()} disabled={tick.isPending}>{tick.isPending ? 'Checking…' : 'Run reminder check now'}</Button>
          <Button variant="secondary" onClick={() => sim.mutate()} disabled={sim.isPending}>{sim.isPending ? 'Simulating…' : '⏩ Simulate next 7 days'}</Button>
          {rows.some((r) => r.simulated) && <Button variant="ghost" onClick={() => clear.mutate()}>Clear simulated</Button>}
        </div>} />
      {msg && <div className="mb-4"><Notice tone={msg.tone}>{msg.text}</Notice></div>}
      <div className="glass mb-5 grid grid-cols-1 gap-3 rounded-[var(--radius-card)] p-4 text-sm sm:grid-cols-3">
        <div><b className="text-red-300">▲ High risk</b><div className="text-muted">In-app + push at 7 days; + WhatsApp at 3 and 1 day and on the due day; repeats every 3 h (max 3), then a family alert.</div></div>
        <div><b className="text-amber-300">● Medium</b><div className="text-muted">Push at 3 days; push + WhatsApp the day before, repeating (max 3).</div></div>
        <div><b className="text-emerald-300">▼ Low</b><div className="text-muted">Push at 7 days and the day before. Quiet hours 21:00–08:00. Paying stops everything.</div></div>
      </div>
      {feed.isLoading && <p className="text-muted">Loading…</p>}
      {rows.length === 0 && !feed.isLoading && <EmptyState>No reminders yet. Press <b className="text-gold">Run reminder check now</b> or <b className="text-gold">Simulate next 7 days</b>.</EmptyState>}
      <ul className="space-y-3">
        {rows.map((r) => {
          const open = r.obligation_status === 'OPEN' || r.obligation_status === 'OVERDUE'
          const first = byBill.get(r.obligation_id)?.id === r.id
          return (
            <li key={r.id} className="glass glass-hover rounded-2xl p-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={CH[r.channel]?.[1] ?? 'slate'}>{CH[r.channel]?.[0] ?? r.channel}</Badge>
                <Badge tone={TIER[r.tier] ?? 'slate'}>{r.tier.toLowerCase()} risk</Badge>
                <Badge>{r.stage === 'OVERDUE' ? 'Overdue' : r.stage.replace('T-', '') === '0' ? 'Due day' : `${r.stage.replace('T-', '')} day(s) before`}{r.attempt_no > 1 ? ` · repeat ${r.attempt_no}` : ''}</Badge>
                <Badge tone={STATUS[r.status]?.[1] ?? 'slate'}>{STATUS[r.status]?.[0] ?? r.status}</Badge>
                {r.simulated && <Badge tone="violet">⏩ simulated</Badge>}
                {r.ack_type && <Badge tone="green">✓ {r.ack_type.replace('_', ' ').toLowerCase()}</Badge>}
                <span className="ml-auto text-xs text-muted">{when(r.scheduled_for)}</span>
              </div>
              <p className="mt-2 text-sm text-ink">{r.message}</p>
              {r.error && <p className="mt-1 text-xs text-amber-300">{r.error}</p>}
              {open && first && (
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button onClick={() => act.mutate([r.obligation_id, 'mark-paid'])} disabled={act.isPending}>✓ I've paid {money(r.amount)}</Button>
                  <Button variant="secondary" onClick={() => act.mutate([r.obligation_id, 'snooze:15'])} disabled={act.isPending}>Snooze 15 min</Button>
                  <Button variant="secondary" onClick={() => act.mutate([r.obligation_id, 'snooze:30'])} disabled={act.isPending}>Snooze 30 min</Button>
                  <Button variant="ghost" onClick={() => act.mutate([r.obligation_id, 'dismiss'])} disabled={act.isPending}>Dismiss</Button>
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
