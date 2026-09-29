import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, day, money, type Subscriptions as Subs } from '../api'
import { Badge, Button, Card, EmptyState, Notice, PageHeader, Stat } from '../ui'

export default function Subscriptions() {
  const q = useQuery({ queryKey: ['subscriptions'], queryFn: () => api<Subs>('/subscriptions') })
  const [note, setNote] = useState<Record<string, string>>({})
  const d = q.data
  const manage = (id: string, url: string | null, what: string) => {
    if (url) { window.open(url, '_blank', 'noopener,noreferrer'); setNote({ ...note, [id]: `Opened the official account page to ${what}. Lifeline never cancels on your behalf.` }) }
    else setNote({ ...note, [id]: `No official account page on file — ${what} it from the app or website you subscribed with.` })
  }
  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader title="Subscriptions" subtitle="Everything that renews on its own — what it costs you each month and year, and where you're paying twice." />
      {q.isLoading && <p className="text-muted">Loading…</p>}
      {d && (
        <div className="space-y-5">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Stat label="Per month" value={money(d.monthly_total)} accent />
            <Stat label="Per year" value={money(d.yearly_total)} />
            <Stat label="Active subscriptions" value={String(d.subscriptions.length)} />
          </div>
          {d.duplicates.map((x) => <Notice key={x.category} tone="warn">💡 You pay for {x.services.length} {x.category.toLowerCase()} services ({x.services.join(', ')}). Keeping one could save money.</Notice>)}
          {d.subscriptions.length === 0 && <EmptyState>No subscriptions detected yet. Upload a bank statement on Connect or forward a receipt.</EmptyState>}
          <div className="space-y-3">
            {d.subscriptions.map((s) => (
              <Card key={s.obligation_id}>
                <div className="flex flex-wrap items-start gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="text-lg font-semibold">{s.biller}</div>
                    <div className="text-sm text-muted">Renews {day(s.next_renewal)} · every {s.interval_days === 365 ? 'year' : 'month'}</div>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {s.price_changed && <Badge tone="amber">Price changed</Badge>}
                      {Number(s.paid_last_12_months) > 0 && <Badge>Paid {money(s.paid_last_12_months)} in the last 12 months</Badge>}
                    </div>
                  </div>
                  <div className="text-right"><div className="num text-2xl font-bold text-gold">{money(s.amount)}</div><div className="text-xs text-muted">≈ {money(s.monthly_cost)}/month</div></div>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  <Button variant="secondary" onClick={() => setNote({ ...note, [s.obligation_id]: 'Kept — Lifeline will remind you before each renewal.' })}>Keep</Button>
                  <Button variant="secondary" onClick={() => manage(s.obligation_id, s.manage_url, 'downgrade')}>Downgrade</Button>
                  <Button variant="danger" onClick={() => manage(s.obligation_id, s.manage_url, 'cancel')}>Cancel</Button>
                </div>
                {note[s.obligation_id] && <div className="mt-3"><Notice tone="info">{note[s.obligation_id]}</Notice></div>}
              </Card>
            ))}
          </div>
          <p className="text-xs text-muted">{d.note}</p>
        </div>
      )}
    </div>
  )
}
