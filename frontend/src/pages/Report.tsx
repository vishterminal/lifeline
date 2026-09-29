import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, day, money, type MonthlyReport } from '../api'
import { Button, Card, PageHeader, Stat } from '../ui'

function shift(month: string, k: number) {
  const [y, m] = month.split('-').map(Number)
  const d = new Date(y, m - 1 + k, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

export default function Report() {
  const now = new Date()
  const [month, setMonth] = useState(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`)
  const r = useQuery({ queryKey: ['report', month], queryFn: () => api<MonthlyReport>(`/report?month=${month}`) }).data
  return (
    <div>
      <PageHeader title="Monthly report" subtitle="What Lifeline did for you this month."
        actions={<div className="flex gap-1 print:hidden">
          <Button variant="secondary" onClick={() => setMonth(shift(month, -1))} aria-label="Previous month">‹</Button>
          <Button variant="secondary" onClick={() => setMonth(shift(month, 1))} aria-label="Next month">›</Button>
          <Button onClick={() => window.print()}>Print / save PDF</Button>
        </div>} />
      {r && (
        <div className="space-y-5">
          <section className="relative overflow-hidden rounded-[var(--radius-card)] bg-gradient-to-br from-gold to-gold-2 p-6 text-bg shadow-[0_18px_40px_-18px_rgb(255_209_0/0.7)]">
            <div className="text-xs font-semibold uppercase tracking-wider opacity-70">{r.label} · penalties avoided</div>
            <div className="num mt-1 text-5xl font-extrabold tracking-tight">{money(r.penalties_avoided)}</div>
            <div className="mt-1 text-sm opacity-80">by paying {r.paid_on_time} bill(s) on time (estimated late fees and lapse costs)</div>
          </section>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Bills paid" value={String(r.paid_count)} hint={money(r.paid_total)} />
            <Stat label="On time" value={`${r.paid_on_time}/${r.paid_count}`} />
            <Stat label="Auto-detected" value={String(r.auto_detected)} hint="closed from a payment SMS/receipt" />
            <Stat label="Reminders sent" value={String(r.reminders_sent)} />
          </div>
          <div className="grid grid-cols-1 gap-5 md:grid-cols-2 [&>*]:min-w-0">
            <Card title={`Coming up · ${r.next_month.label}`}>
              <div className="num text-3xl font-bold text-gold">{money(r.next_month.total)}</div>
              <p className="text-sm text-muted">{r.next_month.count} bill(s) due next month</p>
            </Card>
            <Card title="Subscriptions">
              <div className="num text-3xl font-bold">{money(r.subscriptions.monthly)}<span className="text-base text-muted"> / month</span></div>
              <p className="text-sm text-muted">{r.subscriptions.count} active · <Link to="/subscriptions" className="text-gold hover:underline">review →</Link></p>
            </Card>
          </div>
          <Card title="Needs attention">
            {r.overdue_now.length === 0 ? <p className="text-sm text-muted">Nothing overdue. 🎉</p> : (
              <ul className="space-y-2 text-sm">{r.overdue_now.map((o) => <li key={o.biller + o.due_date}>⚠ {o.biller} — {money(o.amount)}, was due {day(o.due_date)}</li>)}</ul>
            )}
          </Card>
          <p className="text-xs text-muted">{r.note}</p>
        </div>
      )}
    </div>
  )
}
