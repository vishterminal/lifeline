import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, day, money, type Subscriptions as Subs } from '../api'
import { Badge, Button, Card, EmptyState, Notice, PageHeader, Stat } from '../ui'

function daysUntil(iso: string) {
  const today = new Date(); today.setHours(0, 0, 0, 0)
  return Math.round((new Date(iso + 'T00:00:00').getTime() - today.getTime()) / 86_400_000)
}

export default function Subscriptions() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['subscriptions'], queryFn: () => api<Subs>('/subscriptions') })
  const [note, setNote] = useState<Record<string, string>>({})
  const usage = useMutation({
    mutationFn: ({ id, using }: { id: string; using: boolean }) => api(`/subscriptions/${id}/usage`, { method: 'POST', json: { using } }),
    onSuccess: (_d, v) => {
      ['subscriptions', 'bills'].forEach((k) => qc.invalidateQueries({ queryKey: [k] }))
      setNote({ ...note, [v.id]: v.using ? 'Kept: Lifeline will remind you before each renewal.' : 'Marked as not used. Cancel it before the next charge to save this money; Lifeline never cancels on your behalf.' })
    },
  })
  const d = q.data
  const manage = (id: string, url: string | null, what: string) => {
    if (url) { window.open(url, '_blank', 'noopener,noreferrer'); setNote({ ...note, [id]: `Opened the official account page to ${what}. Lifeline never cancels on your behalf.` }) }
    else setNote({ ...note, [id]: `No official account page on file. ${what[0].toUpperCase() + what.slice(1)} it from the app or website you subscribed with.` })
  }
  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader title="Subscriptions" subtitle="Everything that renews on its own: what it costs you each month and year, what charges automatically, and where you're paying twice." />
      {q.isLoading && <p className="text-muted">Loading…</p>}
      {d && (
        <div className="space-y-5">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Stat label="Per month" value={money(d.monthly_total)} accent />
            <Stat label="Per year" value={money(d.yearly_total)} />
            <Stat label="On AutoPay" value={`${d.autopay_count} of ${d.subscriptions.length}`} />
          </div>
          {Number(d.potential_savings_yearly) > 0 && (
            <Notice tone="ok">💰 You said you don't use some of these. Cancelling them saves about <b>{money(d.potential_savings_yearly)} a year</b>.</Notice>
          )}
          {d.duplicates.map((x) => <Notice key={x.category} tone="warn">💡 You pay for {x.services.length} {x.category.toLowerCase()} services ({x.services.join(', ')}). Keeping one could save money.</Notice>)}
          {d.subscriptions.length === 0 && <EmptyState>No subscriptions detected yet. Upload a bank statement on Connect, forward a receipt, or forward your bank's AutoPay pre-debit SMS.</EmptyState>}
          <div className="space-y-3">
            {d.subscriptions.map((s) => {
              const left = daysUntil(s.next_renewal)
              return (
                <Card key={s.obligation_id}>
                  <div className="flex flex-wrap items-start gap-4">
                    <div className="min-w-0 flex-1">
                      <div className="text-lg font-semibold">{s.biller}</div>
                      <div className="text-sm text-muted">Renews {day(s.next_renewal)} · every {s.interval_days === 365 ? 'year' : 'month'}</div>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {s.autopay && <Badge tone="sky">⚡ AutoPay</Badge>}
                        {s.usage === 'USING' && <Badge tone="green">✓ Using it</Badge>}
                        {s.usage === 'NOT_USING' && <Badge tone="red">✗ Not using it</Badge>}
                        {s.price_changed && <Badge tone="amber">Price changed</Badge>}
                        {Number(s.paid_last_12_months) > 0 && <Badge>Paid {money(s.paid_last_12_months)} in the last 12 months</Badge>}
                      </div>
                    </div>
                    <div className="text-right"><div className="num text-2xl font-bold text-gold">{money(s.amount)}</div><div className="text-xs text-muted">≈ {money(s.monthly_cost)}/month</div></div>
                  </div>
                  {s.autopay && left >= 0 && left <= 7 && (
                    <div className="mt-3"><Notice tone={s.usage === 'NOT_USING' ? 'error' : 'warn'}>
                      ⚡ {money(s.amount)} will be charged automatically {left === 0 ? 'today' : left === 1 ? 'tomorrow' : `in ${left} days`}.
                      {s.usage === 'NOT_USING' ? ' You said you don\'t use it. Cancel before it charges.' : ' Cancel before then if you don\'t need it.'}
                    </Notice></div>
                  )}
                  <div className="mt-4 flex flex-wrap items-center gap-2">
                    <span className="mr-1 text-sm text-ink-2">Still using it?</span>
                    <Button variant="secondary" disabled={usage.isPending} onClick={() => usage.mutate({ id: s.obligation_id, using: true })}>Yes, keep</Button>
                    <Button variant="secondary" disabled={usage.isPending} onClick={() => usage.mutate({ id: s.obligation_id, using: false })}>No, not using</Button>
                    <Button variant="secondary" onClick={() => manage(s.obligation_id, s.manage_url, 'downgrade')}>Downgrade</Button>
                    <Button variant="danger" onClick={() => manage(s.obligation_id, s.manage_url, 'cancel')}>Cancel</Button>
                  </div>
                  {note[s.obligation_id] && <div className="mt-3"><Notice tone="info">{note[s.obligation_id]}</Notice></div>}
                </Card>
              )
            })}
          </div>
          <p className="text-xs text-muted">Lifeline can't see whether you watch or listen. It asks you, and reminds you before each automatic charge.</p>
        </div>
      )}
    </div>
  )
}
