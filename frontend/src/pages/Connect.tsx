import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  api, ApiError, when, type GmailSource, type PipelineResult, type SmsSource, type Source, type SyncItem,
  type SyncResult, type WhatsAppSource,
} from '../api'
import { useJudgeMode } from '../judge'
import { OutcomeChip, SampleInbox, SmsSimulator, WhatsAppSimulator } from '../simulators'
import { Button, Card, CopyField, Notice, OUTCOME_TEXT, outcomeTone, StatusBadge } from '../ui'

function useInvalidate() {
  const qc = useQueryClient()
  return () => ['sources', 'confirmations', 'flagged', 'obligations', 'events', 'me'].forEach((k) => qc.invalidateQueries({ queryKey: [k] }))
}

function errText(e: unknown) {
  return e instanceof ApiError ? e.message : 'Something went wrong. Is the backend running?'
}

function ResultNote({ r }: { r: PipelineResult | null }) {
  if (!r) return null
  return (
    <Notice tone={outcomeTone(r.outcome)}>
      {OUTCOME_TEXT[r.outcome] ?? r.outcome}{r.summary ? ` — ${r.summary}` : ''}
      {r.outcome === 'NEEDS_CONFIRMATION' && <> · <Link className="font-semibold underline" to="/inbox">Open Review</Link></>}
    </Notice>
  )
}

// --- Gmail ---------------------------------------------------------------------------
function GmailCard({ src }: { src: GmailSource }) {
  const invalidate = useInvalidate()
  const [params] = useSearchParams()
  const judge = useJudgeMode()
  const [items, setItems] = useState<SyncItem[] | null>(null)
  const [msg, setMsg] = useState<{ tone: 'ok' | 'error' | 'info'; text: string } | null>(null)
  useEffect(() => {
    const g = params.get('gmail')
    if (g === 'connected') setMsg({ tone: 'ok', text: 'Gmail connected. Checking your inbox for bills…' })
    if (g === 'denied') setMsg({ tone: 'error', text: 'Gmail access was not granted.' })
    if (g === 'error') setMsg({ tone: 'error', text: 'Could not connect Gmail. Try again.' })
  }, [params])

  const connect = useMutation({
    mutationFn: () => api<{ auth_url: string }>('/sources/gmail/connect'),
    onSuccess: (r) => { window.location.href = r.auth_url },
    onError: (e) => setMsg({ tone: 'error', text: errText(e) }),
  })
  const sync = useMutation({
    mutationFn: () => api<SyncResult>('/sources/gmail/sync', { method: 'POST' }),
    onSuccess: (r) => {
      invalidate()
      if (r.items) setItems(r.items)
      if (r.status === 'NEEDS_RECONNECT') setMsg({ tone: 'error', text: 'Gmail access expired — reconnect below.' })
      else if (r.status === 'ERROR') setMsg({ tone: 'error', text: r.error ?? 'Could not read Gmail. Try again.' })
      else if (r.fetched === 0) setMsg({ tone: 'info', text: 'Inbox checked — no new bill-like emails since the last check (looks at the last 2 days).' })
      else setMsg({ tone: 'ok', text: `Checked ${r.fetched} bill-like email(s): ${r.saved} added, ${r.needs_review} to review, ${r.flagged} suspicious.` })
    },
    onError: (e) => setMsg({ tone: 'error', text: errText(e) }),
  })
  const disconnect = useMutation({
    mutationFn: () => api('/sources/gmail', { method: 'DELETE' }),
    onSuccess: () => { invalidate(); setMsg({ tone: 'info', text: 'Gmail disconnected and access token deleted.' }) },
  })

  // Auto-sync once right after connecting.
  useEffect(() => {
    if (params.get('gmail') === 'connected' && src.status === 'CONNECTED' && !sync.isPending && !sync.isSuccess) sync.mutate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params, src.status])

  const connected = src.status === 'CONNECTED' || src.status === 'ERROR'
  return (
    <Card icon="✉️" title="Gmail" subtitle="Reads only bill-like emails (read-only access). Checks every 15 minutes." status={<StatusBadge status={src.status} />}>
      <div className="space-y-3">
        {src.status === 'NEEDS_RECONNECT' && <Notice tone="warn">Google access expired (testing-mode tokens last ~7 days). Reconnect to keep collecting.</Notice>}
        {connected ? (
          <>
            <p className="text-sm text-ink-2">
              Connected{src.gmail_address && <> as <b>{src.gmail_address}</b></>} · last checked {when(src.last_sync_at)}
            </p>
            {src.last_error && !msg && <Notice tone="error">{src.last_error}</Notice>}
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => sync.mutate()} disabled={sync.isPending}>{sync.isPending ? 'Checking…' : 'Check inbox now'}</Button>
              <Button variant="danger" onClick={() => disconnect.mutate()}>Disconnect</Button>
            </div>
          </>
        ) : (
          <Button onClick={() => connect.mutate()} disabled={connect.isPending}>
            {src.status === 'NEEDS_RECONNECT' ? 'Reconnect Gmail' : 'Connect Gmail'}
          </Button>
        )}
        {src.mode === 'mock' && (
          <p className="text-xs text-gold/80">Judge mode: Google keys aren't set, so "Connect Gmail" connects a sample inbox with real-world cases — bills, a renewal, a receipt, a newsletter and a phishing email. With keys, the same button opens Google's read-only consent screen for your real inbox.</p>
        )}
        {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
        {judge && connected && <SampleInbox items={items} synced={!!src.last_sync_at} />}
        {!judge && items && items.length > 0 && (
          <ul className="divide-y divide-line rounded-xl border border-line">
            {items.map((i, n) => (
              <li key={n} className="px-3 py-2 text-sm">
                <div className="font-medium">{i.subject}</div>
                <div className="text-xs text-muted">{i.from}</div>
                <div className="mt-1"><OutcomeChip outcome={i.outcome} /></div>
              </li>
            ))}
          </ul>
        )}
        <p className="text-xs text-muted">We store only the extracted details (biller, amount, date) — never the email itself.</p>
      </div>
    </Card>
  )
}

// --- WhatsApp --------------------------------------------------------------------------
function WhatsAppCard({ src }: { src: WhatsAppSource }) {
  const invalidate = useInvalidate()
  const [phone, setPhone] = useState(src.phone_e164 ?? '+91')
  const [err, setErr] = useState<string | null>(null)
  const [reply, setReply] = useState<string | null>(null)
  const link = useMutation({
    mutationFn: () => api('/sources/whatsapp', { method: 'PUT', json: { phone_e164: phone.replace(/\s/g, '') } }),
    onSuccess: () => { setErr(null); invalidate() },
    onError: (e) => setErr(errText(e)),
  })
  const simulate = useMutation({
    mutationFn: () => api<{ reply: string }>('/demo/simulate/whatsapp', { method: 'POST', json: { fixture: 'bill' } }),
    onSuccess: (r) => { setReply(r.reply); invalidate() },
    onError: (e) => setErr(errText(e)),
  })
  const judge = useJudgeMode()
  const sandboxDigits = src.sandbox_number.replace(/\D/g, '')
  const joinText = src.sandbox_join_code || 'join <your-sandbox-code>'
  const waLink = `https://wa.me/${sandboxDigits}?text=${encodeURIComponent(joinText)}`
  const linked = !!src.phone_e164

  return (
    <Card icon="💬" title="WhatsApp" subtitle="Forward any bill, photo or PDF to the Lifeline number." status={<StatusBadge status={judge ? 'CONNECTED' : src.status} />}>
      {judge && (
        <div className="mb-4 grid gap-4 md:grid-cols-2">
          <WhatsAppSimulator />
          <div className="space-y-2 text-sm text-ink-2">
            <p><b>Try it:</b> tap <i>Forward TNEB bill</i> or paste any bill text. Lifeline reads it and replies, exactly as it does on a real phone through the Twilio WhatsApp sandbox.</p>
            <p>Also try <b>WHAT'S DUE</b> and <b>HELP</b>, or send "Hey, dinner tonight?" — it's ignored because it isn't a bill.</p>
            <p className="text-xs text-gold/80">Live version: a real phone forwards to the sandbox number → Twilio (signature-checked) → the same pipeline → reply on WhatsApp.</p>
          </div>
        </div>
      )}
      <details open={!judge} className={judge ? 'rounded-lg bg-surface p-3' : ''}>
      {judge && <summary className="cursor-pointer text-sm font-medium">Live setup with a real phone</summary>}
      <ol className="space-y-4">
        <li>
          <div className="text-sm font-semibold">1. Your WhatsApp number</div>
          <form className="mt-2 flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); link.mutate() }}>
            <label className="sr-only" htmlFor="wa-phone">WhatsApp number</label>
            <input id="wa-phone" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+919876543210"
              className="min-h-11 flex-1 rounded-lg border border-line px-3 py-2 focus:outline-none focus:ring-2 focus:ring-gold/40 focus:border-gold/60" />
            <Button type="submit" variant={linked ? 'secondary' : 'primary'} disabled={link.isPending}>{linked ? 'Update' : 'Save number'}</Button>
          </form>
          <p className="mt-1 text-xs text-muted">With country code, e.g. +91 98765 43210.</p>
        </li>
        <li className={linked ? '' : 'opacity-50'}>
          <div className="text-sm font-semibold">2. Join the Lifeline sandbox (one time)</div>
          <p className="mt-1 text-sm text-ink-2">
            Send <code className="rounded bg-raised px-1.5 py-0.5">{joinText}</code> to <b>+{sandboxDigits}</b> on WhatsApp.
          </p>
          <a href={waLink} target="_blank" rel="noreferrer"
            className="mt-2 inline-flex min-h-11 items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700">
            Open WhatsApp
          </a>
          {!src.sandbox_join_code && (
            <p className="mt-1 text-xs text-amber-300">Set TWILIO_SANDBOX_JOIN_CODE in .env to show your real join code (Twilio console → Messaging → WhatsApp sandbox).</p>
          )}
        </li>
        <li className={linked ? '' : 'opacity-50'}>
          <div className="text-sm font-semibold">3. Forward bills to that number</div>
          <p className="mt-1 text-sm text-ink-2">
            {src.window_open
              ? <>✓ Last message received {when(src.last_inbound_at)}.</>
              : <>No message in the last 24 h. Send any message to the number so Lifeline can reply to you.</>}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button variant="secondary" disabled={!linked || simulate.isPending} onClick={() => simulate.mutate()}>
              Try it: simulate a forwarded bill
            </Button>
          </div>
          {reply && (
            <div className="mt-3 max-w-md rounded-2xl rounded-tl-sm bg-emerald-500/10 px-4 py-3 text-sm whitespace-pre-line">
              <div className="mb-1 text-xs font-semibold text-emerald-300">Lifeline replied</div>{reply}
            </div>
          )}
        </li>
      </ol>
      </details>
      {err && <div className="mt-3"><Notice tone="error">{err}</Notice></div>}
      {src.mode === 'mock' && <p className="mt-3 text-xs text-amber-300">Demo mode: Twilio keys aren't set. Real forwarding needs the Twilio sandbox webhook pointed at {src.webhook_url}.</p>}
    </Card>
  )
}

// --- SMS -------------------------------------------------------------------------------
function SmsCard({ src }: { src: SmsSource }) {
  const invalidate = useInvalidate()
  const [token, setToken] = useState<string | null>(null)
  const [result, setResult] = useState<PipelineResult | null>(null)
  const [testText, setTestText] = useState('TNEB: Your electricity bill of Rs.1840.00 is due on 30 Oct. Pay to avoid late fee.')
  const gen = useMutation({
    mutationFn: () => api<{ token: string }>('/sources/sms/token', { method: 'POST' }),
    onSuccess: (r) => { setToken(r.token); invalidate() },
  })
  const test = useMutation({
    // Uses the real webhook exactly like the phone app would.
    mutationFn: async () => {
      const res = await fetch('/api/ingest/sms', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Ingest-Token': token ?? '' },
        body: JSON.stringify({ sender: 'VM-TNEBLT', text: testText }),
      })
      if (!res.ok) throw new ApiError(res.status, 'ERR', 'Token rejected')
      const events = await api<{ outcome: string; reason: string | null }[]>('/ingest-events?limit=1')
      return { outcome: events[0]?.outcome ?? 'SAVED', reason: events[0]?.reason ?? undefined } as PipelineResult
    },
    onSuccess: (r) => { setResult(r); invalidate() },
  })
  const disconnect = useMutation({
    mutationFn: () => api('/sources/sms', { method: 'DELETE' }),
    onSuccess: () => { setToken(null); invalidate() },
  })
  const judge = useJudgeMode()

  return (
    <Card icon="📱" title="SMS (Android)" subtitle="A free SMS-forwarder app on your phone sends bill SMS to Lifeline." status={<StatusBadge status={judge ? 'CONNECTED' : src.status} />}>
      {judge && (
        <div className="mb-4 grid gap-4 md:grid-cols-2">
          <SmsSimulator />
          <div className="space-y-2 text-sm text-ink-2">
            <p><b>Try it:</b> forward each SMS and watch what Lifeline does. The OTP is dropped instantly and never stored; the personal message is ignored; the bill is tracked.</p>
            <p>Forward the <b>payment debited</b> SMS after confirming the TNEB bill in Review — Lifeline marks the bill paid by itself.</p>
            <p className="text-xs text-gold/80">Live version: an SMS-forwarder app on an Android phone POSTs to <code>/api/ingest/sms</code> with a secret token — the "Live setup" below generates it and even sends a test SMS through the real webhook.</p>
          </div>
        </div>
      )}
      <details open={!judge} className={judge ? 'rounded-lg bg-surface p-3' : ''}>
      {judge && <summary className="cursor-pointer text-sm font-medium">Live setup with a real phone (webhook + token)</summary>}
      <div className="space-y-4">
        {!token && (
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={() => gen.mutate()} disabled={gen.isPending}>{src.has_token ? 'Generate new token' : 'Get my SMS token'}</Button>
            {src.has_token && <Button variant="danger" onClick={() => disconnect.mutate()}>Disconnect</Button>}
            {src.has_token && <span className="text-xs text-muted">A new token replaces the old one on your phone.</span>}
          </div>
        )}
        {token && (
          <div className="space-y-3 rounded-xl border border-amber-400/30 bg-amber-500/10 p-4">
            <Notice tone="warn">Copy this token now — it's shown only once.</Notice>
            <CopyField label="Webhook URL (HTTP POST)" value={src.webhook_url} />
            <CopyField label="Header: X-Ingest-Token" value={token} />
            <div>
              <div className="text-xs font-medium text-muted">Send a test SMS through the real webhook</div>
              <div className="mt-1 flex flex-col gap-2 sm:flex-row">
                <input value={testText} onChange={(e) => setTestText(e.target.value)} aria-label="Test SMS text"
                  className="min-h-11 flex-1 rounded-lg border border-line px-3 py-2 text-sm" />
                <Button onClick={() => test.mutate()} disabled={test.isPending}>Send test</Button>
              </div>
              <div className="mt-2"><ResultNote r={result} /></div>
            </div>
          </div>
        )}
        <p className="text-sm text-ink-2">Last SMS received: {when(src.last_received_at)}</p>
        <details className="rounded-lg bg-surface p-3 text-sm">
          <summary className="cursor-pointer font-medium">Phone setup steps</summary>
          <ol className="mt-2 list-decimal space-y-1 pl-5 text-ink-2">
            {src.checklist.map((s) => <li key={s}>{s}</li>)}
          </ol>
          <p className="mt-2 text-xs text-muted">{src.caveat}</p>
        </details>
        {src.webhook_url.includes('localhost') && (
          <p className="text-xs text-amber-300">Your phone can't reach "localhost". Run a tunnel (ngrok/cloudflared) and set PUBLIC_BASE_URL to use a real phone.</p>
        )}
      </div>
      </details>
    </Card>
  )
}

// --- Upload / manual / statement ------------------------------------------------------------
function OtherInputs() {
  const invalidate = useInvalidate()
  const [upRes, setUpRes] = useState<PipelineResult | null>(null)
  const [upErr, setUpErr] = useState<string | null>(null)
  const [stRes, setStRes] = useState<string | null>(null)
  const [manual, setManual] = useState({ biller: '', type: 'OTHER', amount: '', due_date: '' })
  const [manRes, setManRes] = useState<string | null>(null)

  async function upload(file: File) {
    setUpErr(null); setUpRes(null)
    const fd = new FormData(); fd.append('file', file)
    try { setUpRes(await api<PipelineResult>('/ingest/upload', { method: 'POST', body: fd })); invalidate() }
    catch (e) { setUpErr(errText(e)) }
  }
  async function statement(file: File) {
    setStRes(null)
    const fd = new FormData(); fd.append('file', file)
    try {
      const r = await api<{ charges_found: number; recurring_found: number }>('/ingest/statement', { method: 'POST', body: fd })
      setStRes(`Found ${r.charges_found} payment(s) and ${r.recurring_found} subscription(s).`); invalidate()
    } catch (e) { setStRes(errText(e)) }
  }
  async function addManual(e: React.FormEvent) {
    e.preventDefault()
    try {
      await api('/ingest/manual', { method: 'POST', json: { ...manual, amount: manual.amount || undefined } })
      setManRes('Added to your bills.'); setManual({ biller: '', type: 'OTHER', amount: '', due_date: '' }); invalidate()
    } catch (e) { setManRes(errText(e)) }
  }
  const field = 'min-h-11 rounded-lg border border-line px-3 py-2 text-sm'

  return (
    <Card icon="📎" title="Other ways to add" subtitle="Fallbacks when a bill didn't come through automatically.">
      <div className="grid gap-5 md:grid-cols-3">
        <div className="space-y-2">
          <h3 className="text-sm font-semibold">Photo or PDF of a bill</h3>
          <input type="file" accept="application/pdf,image/png,image/jpeg" aria-label="Upload bill"
            onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} className="block w-full text-sm" />
          <p className="text-xs text-muted">Up to 10 MB.</p>
          <ResultNote r={upRes} />
          {upErr && <Notice tone="error">{upErr}</Notice>}
        </div>
        <form className="space-y-2" onSubmit={addManual}>
          <h3 className="text-sm font-semibold">Type it in</h3>
          <input required placeholder="Biller (e.g. BESCOM)" aria-label="Biller" className={`${field} w-full`} value={manual.biller} onChange={(e) => setManual({ ...manual, biller: e.target.value })} />
          <div className="flex gap-2">
            <input placeholder="Amount ₹" inputMode="decimal" aria-label="Amount" className={`${field} w-1/2`} value={manual.amount} onChange={(e) => setManual({ ...manual, amount: e.target.value })} />
            <input required type="date" aria-label="Due date" className={`${field} w-1/2`} value={manual.due_date} onChange={(e) => setManual({ ...manual, due_date: e.target.value })} />
          </div>
          <select aria-label="Type" className={`${field} w-full`} value={manual.type} onChange={(e) => setManual({ ...manual, type: e.target.value })}>
            {['OTHER', 'ELECTRICITY', 'WATER', 'GAS', 'PHONE_INTERNET', 'INSURANCE_VEHICLE', 'INSURANCE_OTHER', 'PUC', 'DRIVING_LICENCE', 'SUBSCRIPTION', 'LOAN_EMI', 'APPOINTMENT'].map((t) =>
              <option key={t} value={t}>{t.replace(/_/g, ' ').toLowerCase()}</option>)}
          </select>
          <Button type="submit" variant="secondary" className="w-full">Add bill</Button>
          {manRes && <p className="text-xs text-ink-2">{manRes}</p>}
        </form>
        <div className="space-y-2">
          <h3 className="text-sm font-semibold">Bank statement (CSV)</h3>
          <input type="file" accept=".csv,application/pdf" aria-label="Upload bank statement"
            onChange={(e) => e.target.files?.[0] && statement(e.target.files[0])} className="block w-full text-sm" />
          <p className="text-xs text-muted">Finds repeating payments like Netflix. Only merchant, amount and date are kept.</p>
          {stRes && <Notice tone="info">{stRes}</Notice>}
        </div>
      </div>
    </Card>
  )
}

export default function Connect() {
  const sources = useQuery({ queryKey: ['sources'], queryFn: () => api<Source[]>('/sources') })
  if (sources.isLoading) return <p className="text-muted">Loading…</p>
  if (sources.isError) return <Notice tone="error">Couldn't load your sources. <button className="underline" onClick={() => sources.refetch()}>Retry</button></Notice>
  const by = Object.fromEntries((sources.data ?? []).map((s) => [s.kind, s])) as { GMAIL: GmailSource; SMS: SmsSource; WHATSAPP: WhatsAppSource }
  const done = [by.GMAIL.status === 'CONNECTED', by.SMS.status === 'CONNECTED', !!by.WHATSAPP.phone_e164].filter(Boolean).length

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Connect your sources</h1>
        <p className="mt-1.5 text-ink-2">One-time setup. After this, bills are collected automatically.</p>
        <div className="mt-4 flex max-w-md items-center gap-3">
          <div className="h-2 flex-1 overflow-hidden rounded-full bg-surface" role="progressbar" aria-valuemin={0} aria-valuemax={3} aria-valuenow={done} aria-label="Sources connected">
            <div className="h-full rounded-full bg-gold transition-all" style={{ width: `${(done / 3) * 100}%` }} />
          </div>
          <span className="num text-sm font-semibold text-gold">{done} of 3 connected</span>
        </div>
      </div>
      <GmailCard src={by.GMAIL} />
      <WhatsAppCard src={by.WHATSAPP} />
      <SmsCard src={by.SMS} />
      <OtherInputs />
    </div>
  )
}
