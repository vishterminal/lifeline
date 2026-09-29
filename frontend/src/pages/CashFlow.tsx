import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, day, money, type CashflowPlan } from '../api'
import { Badge, Card, EmptyState, Notice, PageHeader, Stat } from '../ui'

/** Single-series balance line (gold), one axis, hover tooltip, hidden table for screen readers. */
function BalanceLine({ points }: { points: CashflowPlan['balance_line'] }) {
  const [hover, setHover] = useState<number | null>(null)
  const W = 720, H = 240, pl = 58, pr = 14, pt = 14, pb = 30
  const vals = points.map((p) => Number(p.balance))
  const max = Math.max(1, ...vals), min = Math.min(0, ...vals)
  const x = (i: number) => pl + (i / Math.max(1, points.length - 1)) * (W - pl - pr)
  const y = (v: number) => pt + (1 - (v - min) / (max - min || 1)) * (H - pt - pb)
  const path = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(Number(p.balance)).toFixed(1)}`).join(' ')
  const ticks = [min, (min + max) / 2, max]
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Projected balance over the planning window"
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => { const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect(); const px = ((e.clientX - r.left) / r.width) * W; setHover(Math.max(0, Math.min(points.length - 1, Math.round(((px - pl) / (W - pl - pr)) * (points.length - 1))))) }}>
        {ticks.map((t) => (
          <g key={t}><line x1={pl} x2={W - pr} y1={y(t)} y2={y(t)} stroke="rgb(247 244 232 / 0.08)" strokeDasharray="3 5" />
            <text x={pl - 8} y={y(t) + 4} textAnchor="end" fontSize="11" fill="#96927D">₹{Math.round(t / 1000)}k</text></g>
        ))}
        {min < 0 && <line x1={pl} x2={W - pr} y1={y(0)} y2={y(0)} stroke="rgb(248 113 113 / 0.5)" />}
        {points.map((p, i) => p.salary && <line key={p.date} x1={x(i)} x2={x(i)} y1={pt} y2={H - pb} stroke="rgb(52 211 153 / 0.35)" strokeDasharray="2 4" />)}
        <path d={path} fill="none" stroke="#FFD100" strokeWidth="2" strokeLinejoin="round" />
        {hover !== null && <><line x1={x(hover)} x2={x(hover)} y1={pt} y2={H - pb} stroke="rgb(247 244 232 / 0.3)" />
          <circle cx={x(hover)} cy={y(vals[hover])} r="4.5" fill="#FFD100" stroke="#211D01" strokeWidth="2" /></>}
        {[0, Math.floor(points.length / 2), points.length - 1].map((i) => points[i] && (
          <text key={i} x={x(i)} y={H - 10} textAnchor="middle" fontSize="11" fill="#96927D">{day(points[i].date).replace(/ \d{4}$/, '')}</text>
        ))}
      </svg>
      {hover !== null && (
        <div className="pointer-events-none absolute top-2 rounded-xl border border-line bg-bg/95 px-3 py-2 text-xs shadow-lg"
          style={{ left: `clamp(0px, calc(${(x(hover) / W) * 100}% - 70px), calc(100% - 150px))` }}>
          <div className="font-semibold text-ink">{day(points[hover].date)}{points[hover].salary ? ' · salary day' : ''}</div>
          <div className="num text-ink-2">{money(points[hover].balance)}</div>
        </div>
      )}
      <table className="sr-only"><caption>Projected balance</caption><tbody>{points.map((p) => <tr key={p.date}><td>{p.date}</td><td>{p.balance}</td></tr>)}</tbody></table>
    </div>
  )
}

export default function CashFlow() {
  const plan = useQuery({ queryKey: ['cashflow'], queryFn: () => api<CashflowPlan>('/cashflow/plan?days=45') })
  const p = plan.data
  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader title="Cash flow" subtitle="When to pay each bill, planned around your salary day and balance — so nothing bounces and the costliest penalties are avoided first." />
      {plan.isLoading && <p className="text-muted">Loading…</p>}
      {p?.needs_balance && <EmptyState>Add your current balance (and salary day) in <Link to="/settings" className="font-semibold text-gold underline">Settings</Link> to plan payments.</EmptyState>}
      {p && !p.needs_balance && (
        <div className="space-y-5">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Stat label="Balance today" value={money(p.start_balance)} hint="snapshot you entered" accent />
            <Stat label="After planned bills" value={money(p.end_balance)} hint="in 45 days" />
            <Stat label="Salary days" value={String(p.salary_days?.length ?? 0)} hint={p.salary_days?.length ? p.salary_days.map((d) => day(d)).join(' · ') : 'set a salary day in Settings'} />
          </div>
          {p.warnings.length > 0 && <div className="space-y-2">{p.warnings.map((w) => <Notice key={w} tone="warn">⚠ {w}</Notice>)}</div>}
          <Card title="Projected balance" subtitle="Gold line = balance · green dashes = salary days">
            <BalanceLine points={p.balance_line} />
          </Card>
          <Card title="Payment schedule">
            {p.schedule.length === 0 ? <p className="text-sm text-muted">No bills with an amount in the next 45 days.</p> : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead><tr className="text-left text-xs uppercase tracking-wider text-muted"><th className="py-2">Bill</th><th>Amount</th><th>Due</th><th>Pay on</th><th>₹ at risk</th><th /></tr></thead>
                  <tbody>{p.schedule.map((s) => (
                    <tr key={s.obligation_id} className="border-t border-white/[0.07]">
                      <td className="py-2.5 font-medium">{s.biller}</td><td className="num">{money(s.amount)}</td><td>{day(s.due_date)}</td>
                      <td>{s.pay_on ? day(s.pay_on) : '—'}</td><td className="num text-gold">{money(s.risk)}</td>
                      <td>{s.status === 'PLANNED' ? <Badge tone="green">✓ Planned</Badge> : <Badge tone="red">⚠ Short</Badge>}</td>
                    </tr>))}</tbody>
                </table>
              </div>
            )}
          </Card>
          <ul className="space-y-1 text-xs text-muted">{p.assumptions.map((a) => <li key={a}>• {a}</li>)}</ul>
        </div>
      )}
    </div>
  )
}
