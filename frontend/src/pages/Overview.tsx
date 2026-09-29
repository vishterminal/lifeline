import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  api, day, money, pretty, when, type Confirmation, type Flagged, type IngestEvent, type Obligation, type RankedBill, type Source, type User,
} from '../api'
import { BarChart, type BarDatum } from '../charts'
import { Badge, Card, EmptyState, OUTCOME_TEXT, OriginBadge, PageHeader, StatusBadge } from '../ui'

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
  const next = open[0]
  const riskOpen = (ranked.data ?? []).filter((b) => OPEN.has(b.status))
  const atRisk = riskOpen.reduce((s, b) => s + Number(b.consequence.direct ?? 0), 0)
  const top = riskOpen[0]
  const firstName = (user?.name || user?.email?.split('@')[0] || '').split(' ')[0]

  return (
    <div>
      <PageHeader
        title={firstName ? `Welcome back, ${firstName}` : 'Overview'}
        subtitle="Everything you owe, in one place — collected automatically from Gmail, WhatsApp and SMS."
        actions={<Link to="/connect" className="inline-flex min-h-11 items-center rounded-xl border border-line-strong bg-surface/60 px-4 text-sm font-medium text-ink hover:border-gold/50">+ Add a source</Link>}
      />

      <div className="grid grid-cols-1 [&>*]:min-w-0 gap-5 lg:grid-cols-12">
        {/* LEFT: My money */}
        <div className="space-y-5 lg:col-span-3">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted">My money</h2>
          <div className="relative overflow-hidden rounded-[var(--radius-card)] bg-gradient-to-br from-gold to-gold-2 p-5 text-bg shadow-[0_18px_40px_-18px_rgb(255_209_0/0.7)]">
            <div className="text-xs font-semibold uppercase tracking-wider opacity-70">Balance snapshot</div>
            <div className="num mt-2 text-3xl font-extrabold tracking-tight">{balance != null ? money(balance) : '—'}</div>
            <div className="mt-1 text-xs opacity-75">
              {balance != null ? <>as of {day(user?.balance_as_of)} · snapshot, not live</> : <Link to="/settings" className="font-semibold underline">Add your balance in Settings</Link>}
            </div>
            <svg className="absolute -bottom-6 -right-6 h-28 w-28 opacity-15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M3 12h4l2.5-6 4 12 2.5-6H21" /></svg>
          </div>
          <ul className="divide-y divide-line overflow-hidden rounded-[var(--radius-card)] border border-line bg-card">
            {[
              ['Penalties at stake', money(atRisk), 'Late fees + lapse costs if missed · estimated'],
              ['Upcoming bills · 30 days', money(due30), `${next30.length} bill${next30.length === 1 ? '' : 's'}`],
              ['Left after bills', afterBills != null ? money(afterBills) : '—', afterBills != null ? (afterBills < 0 ? 'Short before salary' : 'Balance minus 30-day bills') : 'Needs balance'],
              ['Pending review', String(needsReview + suspicious), `${needsReview} to confirm · ${suspicious} suspicious`],
              ['Subscriptions / month', money(monthlySubs), `${subs.length} recurring`],
              ['Paid & closed', String(paid.length), 'Marked paid (incl. auto-detected)'],
            ].map(([k, v, hint]) => (
              <li key={k} className="px-4 py-3.5">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-sm text-ink-2">{k}</span>
                  <span className={`num text-base font-bold ${k === 'Left after bills' && afterBills != null && afterBills < 0 ? 'text-red-300' : 'text-ink'}`}>{v}</span>
                </div>
                <div className="text-xs text-muted">{hint}</div>
              </li>
            ))}
          </ul>
          {user?.salary_day && <p className="px-1 text-xs text-muted">Salary day: {user.salary_day} of each month.</p>}
        </div>

        {/* MAIN: analytics */}
        <div className="space-y-5 lg:col-span-6">
          <Card>
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

          <Card title="Next up" subtitle="Soonest open bills">
            {open.length === 0 ? <p className="text-sm text-muted">Nothing due.</p> : (
              <ul className="divide-y divide-line">
                {open.slice(0, 5).map((o) => (
                  <li key={o.id} className="flex items-center gap-3 py-3">
                    <div className={`h-10 w-1 rounded-full ${daysUntil(o.due_date) <= 1 ? 'bg-red-400' : daysUntil(o.due_date) <= 7 ? 'bg-gold' : 'bg-line-strong'}`} aria-hidden="true" />
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium">{o.biller_raw ?? o.biller_norm}</div>
                      <div className="text-xs text-muted">{pretty(o.type)} · {day(o.due_date)}</div>
                    </div>
                    <div className="text-right">
                      <div className="num font-semibold">{money(o.amount)}</div>
                      <div className={`text-xs ${daysUntil(o.due_date) < 0 ? 'text-red-300' : 'text-muted'}`}>{dueText(o.due_date)}</div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            {open.length > 5 && <Link to="/bills" className="mt-2 inline-block text-sm font-medium text-gold hover:underline">All bills →</Link>}
          </Card>
        </div>

        {/* RIGHT: stacked summaries */}
        <div className="space-y-5 lg:col-span-3">
          {top && (
            <Card title="Highest ₹ risk">
              <div className="font-semibold">{top.biller_raw ?? top.biller_norm}</div>
              <div className="num mt-1 text-3xl font-bold text-gold">{money(top.consequence.total)}</div>
              <p className="text-sm text-muted">at risk · {dueText(top.due_date).toLowerCase()}</p>
              {top.chain_hint && <p className="mt-2 rounded-lg border border-amber-400/25 bg-amber-500/10 px-2.5 py-1.5 text-xs text-amber-200">⛓ {top.chain_hint}</p>}
              <Link to="/bills" className="mt-3 inline-block text-sm font-medium text-gold hover:underline">See ranking →</Link>
            </Card>
          )}
          <Card title="This week">
            <div className="num text-3xl font-bold text-ink">{money(thisWeek.reduce((s, o) => s + num(o.amount), 0))}</div>
            <p className="text-sm text-muted">{thisWeek.length} bill{thisWeek.length === 1 ? '' : 's'} due in the next 7 days</p>
          </Card>
          <Card title="Alerts">
            <ul className="space-y-2.5 text-sm">
              <AlertRow on={overdue.length > 0} tone="red" text={`${overdue.length} overdue bill${overdue.length === 1 ? '' : 's'}`} to="/bills" />
              <AlertRow on={suspicious > 0} tone="red" text={`${suspicious} suspicious message${suspicious === 1 ? '' : 's'} blocked`} to="/inbox" />
              <AlertRow on={needsReview > 0} tone="amber" text={`${needsReview} item${needsReview === 1 ? '' : 's'} waiting for your confirmation`} to="/inbox" />
              <AlertRow on={subs.some((s) => s.price_changed)} tone="amber" text="A subscription price changed" to="/bills" />
              {overdue.length + suspicious + needsReview === 0 && !subs.some((s) => s.price_changed) && <li className="text-muted">All clear — nothing needs you.</li>}
            </ul>
          </Card>
          <Card title="Sources">
            <div className="num text-3xl font-bold">{connected}<span className="text-lg text-muted">/3</span></div>
            <p className="mb-3 text-sm text-muted">collecting automatically</p>
            <ul className="space-y-2">
              {(sources.data ?? []).map((s) => (
                <li key={s.kind} className="flex items-center justify-between text-sm">
                  <span className="text-ink-2">{s.kind === 'GMAIL' ? 'Gmail' : s.kind === 'SMS' ? 'SMS' : 'WhatsApp'}</span>
                  <StatusBadge status={s.status} />
                </li>
              ))}
            </ul>
          </Card>
        </div>

        {/* LOWER */}
        <div className="lg:col-span-4">
          <Card title="Upcoming payment" className="h-full">
            {next ? (
              <>
                <div className="text-sm text-muted">{pretty(next.type)}</div>
                <div className="mt-1 text-xl font-semibold">{next.biller_raw ?? next.biller_norm}</div>
                <div className="num mt-3 text-3xl font-bold text-gold">{money(next.amount)}</div>
                <div className="mt-1 text-sm text-ink-2">{day(next.due_date)} · {dueText(next.due_date)}</div>
                <div className="mt-3 flex flex-wrap gap-1.5"><OriginBadge origin={next.origin} />{next.source_kinds.map((k) => <Badge key={k}>from {pretty(k)}</Badge>)}</div>
              </>
            ) : <p className="text-sm text-muted">Nothing due.</p>}
          </Card>
        </div>
        <div className="lg:col-span-4">
          <Card title="Recent activity" className="h-full">
            {(events.data ?? []).length === 0 ? <p className="text-sm text-muted">No messages processed yet.</p> : (
              <ul className="space-y-3">
                {events.data!.map((e) => (
                  <li key={e.id} className="text-sm">
                    <div className="flex justify-between gap-2"><span className="font-medium">{pretty(e.source_kind)}</span><span className="text-xs text-muted">{when(e.received_at)}</span></div>
                    <div className="text-ink-2">{OUTCOME_TEXT[e.outcome] ?? e.outcome}</div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
        <div className="lg:col-span-4">
          <Card title="Subscriptions" className="h-full">
            {subs.length === 0 ? <p className="text-sm text-muted">No recurring charges detected yet. Upload a bank statement on Connect to find them.</p> : (
              <ul className="space-y-3">
                {subs.map((s) => (
                  <li key={s.id} className="flex items-center justify-between gap-3 text-sm">
                    <div className="min-w-0">
                      <div className="truncate font-medium">{s.biller_raw ?? s.biller_norm}</div>
                      <div className="text-xs text-muted">Renews {day(s.next_expected_date ?? s.due_date)}{s.price_changed ? ' · price changed' : ''}</div>
                    </div>
                    <span className="num font-semibold">{money(s.amount)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
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
