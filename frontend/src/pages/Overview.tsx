import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  api, day, money, pretty, when, type Confirmation, type Flagged, type IngestEvent, type Obligation, type Lifeload, type RankedBill, type Source, type User,
} from '../api'
import { BarChart, type BarDatum } from '../charts'
import { Card, EmptyState, OUTCOME_TEXT, PageHeader, StatusBadge } from '../ui'

const OPEN = new Set(['OPEN', 'OVERDUE'])
const DAY_MS = 86_400_000

function startOfToday() {
  const d = new Date(); d.setHours(0, 0, 0, 0); return d
}
function toDate(iso: string) { return new Date(iso + 'T00:00:00') }
function daysUntil(iso: string) { return Math.round((toDate(iso).getTime() - startOfToday().getTime()) / DAY_MS) }
function num(v: string | null) { return v ? Number(v) : 0 }
function dueText(iso: string) {
  const d = daysUntil(iso)
  return d === 0 ? 'Due today' : d === 1 ? 'Due tomorrow' : d < 0 ? `${-d}d overdue` : `In ${d} days`
}

export default function Overview() {
  const me = useQuery({ queryKey: ['me'], queryFn: () => api<{ user: User }>('/auth/me') })
  const obls = useQuery({ queryKey: ['obligations'], queryFn: () => api<Obligation[]>('/obligations'), refetchInterval: 30_000 })
  const confs = useQuery({ queryKey: ['confirmations'], queryFn: () => api<Confirmation[]>('/confirmations') })
  const flagged = useQuery({ queryKey: ['flagged'], queryFn: () => api<Flagged[]>('/flagged') })
  const events = useQuery({ queryKey: ['events'], queryFn: () => api<IngestEvent[]>('/ingest-events?limit=6') })
  const sources = useQuery({ queryKey: ['sources'], queryFn: () => api<Source[]>('/sources') })
  const load = useQuery({ queryKey: ['lifeload'], queryFn: () => api<Lifeload>('/lifeload'), refetchInterval: 30_000 })
  const ranked = useQuery({ queryKey: ['bills', 'risk'], queryFn: () => api<RankedBill[]>('/bills?sort=risk'), refetchInterval: 30_000 })

  const user = me.data?.user
  const all = obls.data ?? []
  const open = all.filter((o) => OPEN.has(o.status)).sort((a, b) => a.due_date.localeCompare(b.due_date))
  const next30 = open.filter((o) => daysUntil(o.due_date) <= 30)
  const thisWeek = open.filter((o) => daysUntil(o.due_date) <= 7)
  const overdue = open.filter((o) => o.status === 'OVERDUE' || daysUntil(o.due_date) < 0)
  const subs = all.filter((o) => o.is_recurring && OPEN.has(o.status))
  const monthlySubs = subs.reduce((s, o) => s + num(o.amount) * (o.recurrence_interval_days && o.recurrence_interval_days > 40 ? 30 / o.recurrence_interval_days : 1), 0)
  const paid = all.filter((o) => o.status === 'PAID')
  const due30 = next30.reduce((s, o) => s + num(o.amount), 0)
  const balance = user?.balance_amount != null ? Number(user.balance_amount) : null
  const afterBills = balance != null ? balance - due30 : null
  const needsReview = (confs.data?.length ?? 0)
  const suspicious = flagged.data?.length ?? 0
  const connected = (sources.data ?? []).filter((s) => s.status === 'CONNECTED').length

  // Upcoming payments per week, next 8 weeks (real obligations).
  const weeks: BarDatum[] = Array.from({ length: 8 }, (_, i) => {
    const start = new Date(startOfToday().getTime() + i * 7 * DAY_MS)
    const end = new Date(start.getTime() + 6 * DAY_MS)
    const inWeek = open.filter((o) => { const d = daysUntil(o.due_date); return i === 0 ? d <= 6 : d >= i * 7 && d <= i * 7 + 6 })
    const fmt = (d: Date) => d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
    return { label: i === 0 ? 'This wk' : fmt(start), sub: `${fmt(start)} – ${fmt(end)}`, value: inWeek.reduce((s, o) => s + num(o.amount), 0), count: inWeek.length }
  })
  const riskOpen = (ranked.data ?? []).filter((b) => OPEN.has(b.status))
  const atRisk = riskOpen.reduce((s, b) => s + Number(b.consequence.direct ?? 0), 0)
  const top = riskOpen[0]

  return (
    <div>
      <PageHeader
        title="Overview"
        subtitle="Everything you owe, in one place — collected automatically from Gmail, WhatsApp and SMS."
        actions={<Link to="/connect" className="inline-flex min-h-11 items-center rounded-xl border border-line-strong bg-surface/60 px-4 text-sm font-medium text-ink hover:border-gold/50">+ Add a source</Link>}
      />

      {/* ROW 1: key numbers, equal tiles */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4 [&>*]:min-w-0">
        <div className="relative overflow-hidden rounded-[var(--radius-card)] bg-gradient-to-br from-gold to-gold-2 p-5 text-bg shadow-[0_18px_40px_-18px_rgb(255_209_0/0.7)]">
          <div className="text-xs font-semibold uppercase tracking-wider opacity-70">Balance snapshot</div>
          <div className="num mt-2 text-3xl font-extrabold tracking-tight">{balance != null ? money(balance) : '—'}</div>
          <div className="mt-1 text-xs opacity-75">
            {balance != null ? <>as of {day(user?.balance_as_of)} · not live</> : <Link to="/settings" className="font-semibold underline">Add your balance in Settings</Link>}
          </div>
          <svg className="absolute -bottom-6 -right-6 h-28 w-28 opacity-15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M3 12h4l2.5-6 4 12 2.5-6H21" /></svg>
        </div>
        <Tile label="Penalties at stake" value={money(atRisk)} hint="Late fees + lapse costs if missed · estimated" accent />
        <Tile label="Due in 30 days" value={money(due30)} hint={`${next30.length} bill${next30.length === 1 ? '' : 's'} · ${money(thisWeek.reduce((s, o) => s + num(o.amount), 0))} this week`} />
        <Tile label="Left after bills" value={afterBills != null ? money(afterBills) : '—'} danger={afterBills != null && afterBills < 0}
          hint={afterBills != null ? (afterBills < 0 ? 'Short before salary' : 'Balance minus 30-day bills') : 'Needs your balance'} />
      </div>

      {/* ROW 2: chart + life-load, same height */}
      <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-3 [&>*]:min-w-0">
        <Card className="h-full lg:col-span-2">
          <div className="mb-4 flex flex-wrap items-end gap-3">
            <div className="flex-1">
              <h2 className="text-lg font-semibold">Upcoming payments</h2>
              <p className="text-sm text-muted">Amount due per week, next 8 weeks</p>
            </div>
            <div className="text-right">
              <div className="num text-2xl font-bold text-gold">{money(weeks.reduce((s, w) => s + w.value, 0))}</div>
              <div className="text-xs text-muted">{open.length} open bill{open.length === 1 ? '' : 's'}</div>
            </div>
          </div>
          {open.length === 0
            ? <EmptyState>No upcoming bills yet. <Link to="/connect" className="font-semibold text-gold underline">Connect a source</Link> or run the demo.</EmptyState>
            : <BarChart data={weeks} title="Amount due per week for the next 8 weeks" />}
        </Card>
        <Card title="Life-load" subtitle="How heavy your next 7 days are" className="h-full">
          <div className="flex flex-col items-center justify-center pt-2">
            <Gauge score={load.data?.score ?? 0} />
            <p className="mt-3 text-center text-sm text-muted">{load.data ? `${load.data.label} week · ${load.data.items_next_7_days} due in 7 days` : ' '}</p>
          </div>
        </Card>
      </div>

      {/* ROW 3: three equal cards */}
      <div className="mt-5 grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-3 [&>*]:min-w-0">
        <Card title="Next up" subtitle="Soonest open bills" className="h-full">
          {open.length === 0 ? <p className="text-sm text-muted">Nothing due.</p> : (
            <ul className="divide-y divide-line">
              {open.slice(0, 4).map((o) => (
                <li key={o.id} className="flex items-center gap-3 py-2.5">
                  <div className={`h-9 w-1 shrink-0 rounded-full ${daysUntil(o.due_date) <= 1 ? 'bg-red-400' : daysUntil(o.due_date) <= 7 ? 'bg-gold' : 'bg-line-strong'}`} aria-hidden="true" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium">{o.biller_raw ?? o.biller_norm}</div>
                    <div className="truncate text-xs text-muted">{pretty(o.type)} · {day(o.due_date)}</div>
                  </div>
                  <div className="shrink-0 text-right">
                    <div className="num font-semibold">{money(o.amount)}</div>
                    <div className={`text-xs ${daysUntil(o.due_date) < 0 ? 'text-red-300' : 'text-muted'}`}>{dueText(o.due_date)}</div>
                  </div>
                </li>
              ))}
            </ul>
          )}
          {open.length > 4 && <Link to="/bills" className="mt-2 inline-block text-sm font-medium text-gold hover:underline">All bills →</Link>}
        </Card>
        <Card title="Highest ₹ risk" subtitle="What missing it would cost" className="h-full">
          {top ? (
            <>
              <div className="font-semibold">{top.biller_raw ?? top.biller_norm}</div>
              <div className="num mt-1 text-3xl font-bold text-gold">{money(top.consequence.total)}</div>
              <p className="text-sm text-muted">at risk · {dueText(top.due_date).toLowerCase()}</p>
              {top.chain_hint && <p className="mt-3 rounded-lg border border-amber-400/25 bg-amber-500/10 px-2.5 py-1.5 text-xs text-amber-200">⛓ {top.chain_hint}</p>}
              <Link to="/bills" className="mt-3 inline-block text-sm font-medium text-gold hover:underline">See ranking →</Link>
            </>
          ) : <p className="text-sm text-muted">No open bills to rank yet.</p>}
        </Card>
        <Card title="Subscriptions" subtitle={`${money(monthlySubs)} a month`} className="h-full" status={<Link to="/subscriptions" className="text-sm font-medium text-gold hover:underline">Manage →</Link>}>
          {subs.length === 0 ? <p className="text-sm text-muted">No recurring charges detected yet. Upload a bank statement on Connect to find them.</p> : (
            <ul className="space-y-3">
              {subs.slice(0, 4).map((s) => (
                <li key={s.id} className="flex items-center justify-between gap-3 text-sm">
                  <div className="min-w-0">
                    <div className="truncate font-medium">{s.biller_raw ?? s.biller_norm}{s.autopay ? ' ⚡' : ''}</div>
                    <div className="text-xs text-muted">Renews {day(s.next_expected_date ?? s.due_date)}{s.price_changed ? ' · price changed' : ''}</div>
                  </div>
                  <span className="num shrink-0 font-semibold">{money(s.amount)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {/* ROW 4: three equal cards */}
      <div className="mt-5 grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-3 [&>*]:min-w-0">
        <Card title="Alerts" className="h-full">
          <ul className="space-y-2.5 text-sm">
            <AlertRow on={overdue.length > 0} tone="red" text={`${overdue.length} overdue bill${overdue.length === 1 ? '' : 's'}`} to="/bills" />
            <AlertRow on={suspicious > 0} tone="red" text={`${suspicious} suspicious message${suspicious === 1 ? '' : 's'} blocked`} to="/inbox" />
            <AlertRow on={needsReview > 0} tone="amber" text={`${needsReview} item${needsReview === 1 ? '' : 's'} waiting for your confirmation`} to="/inbox" />
            <AlertRow on={subs.some((s) => s.price_changed)} tone="amber" text="A subscription price changed" to="/subscriptions" />
            {overdue.length + suspicious + needsReview === 0 && !subs.some((s) => s.price_changed) && <li className="text-muted">All clear — nothing needs you.</li>}
          </ul>
          <div className="mt-4 border-t border-line pt-3 text-sm text-ink-2">✓ {paid.length} bill{paid.length === 1 ? '' : 's'} paid &amp; closed</div>
        </Card>
        <Card title="Sources" subtitle="Collecting automatically" className="h-full" status={<span className="num text-2xl font-bold">{connected}<span className="text-base text-muted">/3</span></span>}>
          <ul className="space-y-2.5">
            {(sources.data ?? []).map((s) => (
              <li key={s.kind} className="flex items-center justify-between text-sm">
                <span className="text-ink-2">{s.kind === 'GMAIL' ? 'Gmail' : s.kind === 'SMS' ? 'SMS' : 'WhatsApp'}</span>
                <StatusBadge status={s.status} />
              </li>
            ))}
          </ul>
          {user?.salary_day && <p className="mt-4 border-t border-line pt-3 text-sm text-ink-2">Salary day: {user.salary_day} of each month</p>}
        </Card>
        <Card title="Recent activity" className="h-full">
          {(events.data ?? []).length === 0 ? <p className="text-sm text-muted">No messages processed yet.</p> : (
            <ul className="space-y-2.5">
              {events.data!.slice(0, 4).map((e) => (
                <li key={e.id} className="text-sm">
                  <div className="flex justify-between gap-2"><span className="font-medium">{pretty(e.source_kind)}</span><span className="text-xs text-muted">{when(e.received_at)}</span></div>
                  <div className="truncate text-ink-2">{OUTCOME_TEXT[e.outcome] ?? e.outcome}</div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  )
}

function Gauge({ score }: { score: number }) {
  const r = 70, c = Math.PI * r, pct = Math.max(0, Math.min(100, score)) / 100
  const color = score >= 60 ? '#f87171' : score >= 30 ? '#FFD100' : '#34d399'
  return (
    <svg viewBox="0 0 180 110" className="mx-auto h-auto w-full max-w-[220px]" role="img" aria-label={`Life-load score ${score} out of 100`}>
      <path d="M20 95 A70 70 0 0 1 160 95" fill="none" stroke="rgb(247 244 232 / 0.1)" strokeWidth="14" strokeLinecap="round" />
      <path d="M20 95 A70 70 0 0 1 160 95" fill="none" stroke={color} strokeWidth="14" strokeLinecap="round" strokeDasharray={`${c * pct} ${c}`} />
      <text x="90" y="88" textAnchor="middle" fontSize="30" fontWeight="800" fill="#F7F4E8">{score}</text>
      <text x="90" y="104" textAnchor="middle" fontSize="10" fill="#96927D">out of 100</text>
    </svg>
  )
}

function Tile({ label, value, hint, accent = false, danger = false }: { label: string; value: string; hint: string; accent?: boolean; danger?: boolean }) {
  return (
    <div className="glass rounded-[var(--radius-card)] p-5">
      <div className="text-xs font-semibold uppercase tracking-wider text-muted">{label}</div>
      <div className={`num mt-2 text-3xl font-extrabold tracking-tight ${danger ? 'text-red-300' : accent ? 'text-gold' : 'text-ink'}`}>{value}</div>
      <div className="mt-1 text-xs text-muted">{hint}</div>
    </div>
  )
}

function AlertRow({ on, tone, text, to }: { on: boolean; tone: 'red' | 'amber'; text: string; to: string }) {
  if (!on) return null
  return (
    <li>
      <Link to={to} className="flex items-start gap-2 hover:text-gold">
        <span aria-hidden="true" className={tone === 'red' ? 'text-red-300' : 'text-amber-300'}>{tone === 'red' ? '⚠' : '●'}</span>
        <span className="text-ink-2">{text}</span>
      </Link>
    </li>
  )
}
