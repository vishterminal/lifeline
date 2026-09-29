import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { api, day, money, pretty, type Obligation } from '../api'
import { Badge, Button, Card, OriginBadge, PageHeader } from '../ui'

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

export default function CalendarPage() {
  const obls = useQuery({ queryKey: ['obligations'], queryFn: () => api<Obligation[]>('/obligations') })
  const today = new Date()
  const [cursor, setCursor] = useState(new Date(today.getFullYear(), today.getMonth(), 1))
  const [selected, setSelected] = useState<string>(iso(today))

  const byDay = useMemo(() => {
    const m: Record<string, Obligation[]> = {}
    for (const o of obls.data ?? []) (m[o.due_date] ??= []).push(o)
    return m
  }, [obls.data])

  const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1)
  const offset = (first.getDay() + 6) % 7 // Monday-first
  const daysInMonth = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0).getDate()
  const cells = Array.from({ length: Math.ceil((offset + daysInMonth) / 7) * 7 }, (_, i) => {
    const n = i - offset + 1
    return n >= 1 && n <= daysInMonth ? new Date(cursor.getFullYear(), cursor.getMonth(), n) : null
  })
  const monthTotal = Object.entries(byDay)
    .filter(([d]) => d.startsWith(iso(first).slice(0, 7)))
    .flatMap(([, list]) => list).filter((o) => o.status !== 'PAID' && o.status !== 'DISMISSED')
    .reduce((s, o) => s + Number(o.amount ?? 0), 0)
  const sel = byDay[selected] ?? []
  const move = (k: number) => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + k, 1))

  return (
    <div>
      <PageHeader title="Calendar" subtitle="Every due date and renewal Lifeline has found, by day." />
      <div className="grid grid-cols-1 [&>*]:min-w-0 gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <h2 className="flex-1 text-xl font-semibold">{cursor.toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })}</h2>
            <span className="text-sm text-muted">Open this month: <b className="num text-gold">{money(monthTotal)}</b></span>
            <div className="flex gap-1">
              <Button variant="secondary" onClick={() => move(-1)} aria-label="Previous month">‹</Button>
              <Button variant="secondary" onClick={() => { setCursor(new Date(today.getFullYear(), today.getMonth(), 1)); setSelected(iso(today)) }}>Today</Button>
              <Button variant="secondary" onClick={() => move(1)} aria-label="Next month">›</Button>
            </div>
          </div>
          <div className="grid grid-cols-7 gap-1 text-center text-xs font-medium uppercase tracking-wider text-muted">
            {WEEKDAYS.map((w) => <div key={w} className="py-2">{w}</div>)}
          </div>
          <div className="grid grid-cols-7 gap-1">
            {cells.map((d, i) => {
              if (!d) return <div key={i} className="aspect-square rounded-xl sm:aspect-auto sm:min-h-24" />
              const k = iso(d)
              const items = byDay[k] ?? []
              const isToday = k === iso(today)
              const isSel = k === selected
              const openItems = items.filter((o) => o.status !== 'PAID' && o.status !== 'DISMISSED')
              return (
                <button key={k} onClick={() => setSelected(k)} aria-pressed={isSel} aria-label={`${day(k)}: ${items.length} bill(s)`}
                  className={`flex aspect-square flex-col rounded-xl border p-1.5 text-left transition sm:aspect-auto sm:min-h-24 ${isSel ? 'border-gold bg-gold/10' : 'border-line bg-surface/50 hover:border-gold/40'}`}>
                  <span className={`grid h-6 w-6 place-items-center rounded-full text-xs font-semibold ${isToday ? 'bg-gold text-bg' : 'text-ink-2'}`}>{d.getDate()}</span>
                  <span className="mt-auto hidden space-y-1 sm:block">
                    {items.slice(0, 2).map((o) => (
                      <span key={o.id} className={`block truncate rounded-md px-1.5 py-0.5 text-[11px] ${o.status === 'PAID' ? 'bg-emerald-500/12 text-emerald-300 line-through' : 'bg-gold/15 text-gold'}`}>
                        {o.biller_raw ?? o.biller_norm}
                      </span>
                    ))}
                    {items.length > 2 && <span className="block text-[11px] text-muted">+{items.length - 2} more</span>}
                  </span>
                  {openItems.length > 0 && <span className="mt-auto h-1.5 w-1.5 self-center rounded-full bg-gold sm:hidden" aria-hidden="true" />}
                </button>
              )
            })}
          </div>
        </Card>
        <Card title={day(selected)} subtitle={sel.length ? `${sel.length} item${sel.length === 1 ? '' : 's'}` : 'Nothing due this day'}>
          <ul className="space-y-3">
            {sel.map((o) => (
              <li key={o.id} className="rounded-2xl border border-line bg-surface/60 p-4">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-semibold">{o.biller_raw ?? o.biller_norm}</span>
                  <span className="num font-bold text-gold">{money(o.amount)}</span>
                </div>
                <div className="mt-1 text-xs text-muted">{pretty(o.type)} · {o.is_recurring ? 'renewal' : 'due'} · {pretty(o.status)}</div>
                <div className="mt-2 flex flex-wrap gap-1.5"><OriginBadge origin={o.origin} />{o.source_kinds.map((k) => <Badge key={k}>from {pretty(k)}</Badge>)}</div>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  )
}
