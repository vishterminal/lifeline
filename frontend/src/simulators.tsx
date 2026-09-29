// Phone-style simulators used in judge mode. They call the same pipeline the
// live Twilio / SMS-forwarder webhooks call.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Fixtures, type InboxMail, type PipelineResult, type SyncItem } from './api'
import { invalidateAll } from './judge'
import { OUTCOME_TEXT, outcomeTone } from './ui'

const TONE: Record<string, string> = {
  ok: 'bg-emerald-500/15 text-emerald-300', warn: 'bg-amber-500/15 text-amber-300',
  error: 'bg-red-500/15 text-red-300', info: 'bg-raised text-ink-2',
}

export function OutcomeChip({ outcome }: { outcome: string }) {
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-semibold ${TONE[outcomeTone(outcome)]}`}>
      {OUTCOME_TEXT[outcome] ?? outcome}
    </span>
  )
}

function PhoneFrame({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <div className="mx-auto w-full max-w-sm overflow-hidden rounded-[2rem] border-8 border-black bg-black shadow-xl">
      <div className="bg-black px-4 pb-2 pt-1 text-center text-[10px] text-muted">●  ●  ●</div>
      <div className="bg-emerald-700 px-4 py-2 text-white">
        <div className="text-sm font-semibold">{title}</div>
        <div className="text-xs opacity-80">{subtitle}</div>
      </div>
      {children}
    </div>
  )
}

// --- WhatsApp chat -------------------------------------------------------------------------
type Msg = { from: 'me' | 'bot'; text: string }

export function WhatsAppSimulator() {
  const qc = useQueryClient()
  const fx = useQuery({ queryKey: ['fixtures'], queryFn: () => api<Fixtures>('/demo/fixtures') })
  const [msgs, setMsgs] = useState<Msg[]>([
    { from: 'bot', text: 'Hi! Forward me any bill, renewal notice or receipt and I\'ll track it. Send HELP for commands.' },
  ])
  const [text, setText] = useState('')
  const send = useMutation({
    mutationFn: (t: string) => api<{ reply: string }>('/demo/simulate/whatsapp', { method: 'POST', json: { text: t } }),
    onMutate: (t) => setMsgs((m) => [...m, { from: 'me', text: t }]),
    onSuccess: (r) => { setMsgs((m) => [...m, { from: 'bot', text: r.reply }]); invalidateAll(qc) },
    onError: (e) => setMsgs((m) => [...m, { from: 'bot', text: `⚠ ${(e as Error).message}` }]),
  })
  const submit = (t: string) => { if (t.trim()) { send.mutate(t.trim()); setText('') } }

  return (
    <PhoneFrame title="Lifeline" subtitle="WhatsApp · simulated sandbox">
      <div className="h-72 space-y-2 overflow-y-auto bg-[#efeae2] p-3" aria-live="polite">
        {msgs.map((m, i) => (
          <div key={i} className={`flex ${m.from === 'me' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[85%] whitespace-pre-line rounded-lg px-3 py-2 text-sm shadow-sm ${m.from === 'me' ? 'bg-[#d9fdd3]' : 'bg-card'}`}>
              {m.text}
            </div>
          </div>
        ))}
        {send.isPending && <div className="text-xs text-muted">Lifeline is typing…</div>}
      </div>
      <div className="flex flex-wrap gap-1 bg-card px-2 pt-2">
        {fx.data?.whatsapp.map((f) => (
          <button key={f.id} onClick={() => submit(f.text)} disabled={send.isPending}
            className="rounded-full border border-emerald-400/30 bg-emerald-500/10 px-2.5 py-1 text-xs text-emerald-300 hover:bg-emerald-500/20">
            {f.id === 'bill' ? '↪ Forward TNEB bill' : f.id === 'puc' ? '↪ Forward PUC notice' : f.text}
          </button>
        ))}
      </div>
      <form className="flex gap-2 bg-card p-2" onSubmit={(e) => { e.preventDefault(); submit(text) }}>
        <label htmlFor="wa-sim" className="sr-only">Message</label>
        <input id="wa-sim" value={text} onChange={(e) => setText(e.target.value)} placeholder="Type or paste a bill…"
          className="min-h-11 flex-1 rounded-full border border-line px-4 text-sm" />
        <button className="min-h-11 rounded-full bg-emerald-600 px-4 text-sm font-medium text-white" disabled={send.isPending}>Send</button>
      </form>
    </PhoneFrame>
  )
}

// --- SMS inbox ------------------------------------------------------------------------------
export function SmsSimulator() {
  const qc = useQueryClient()
  const fx = useQuery({ queryKey: ['fixtures'], queryFn: () => api<Fixtures>('/demo/fixtures') })
  const [results, setResults] = useState<Record<string, PipelineResult>>({})
  const fwd = useMutation({
    mutationFn: (id: string) => api<PipelineResult>('/demo/simulate/sms', { method: 'POST', json: { fixture: id } }),
    onSuccess: (r, id) => { setResults((x) => ({ ...x, [id]: r })); invalidateAll(qc) },
  })
  return (
    <PhoneFrame title="Messages" subtitle="Android · forwarder app sends bill SMS to Lifeline">
      <ul className="max-h-[26rem] divide-y divide-line overflow-y-auto bg-card">
        {fx.data?.sms.map((s) => (
          <li key={s.id} className="p-3">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-sm font-semibold">{s.sender}</span>
              <span className="text-[11px] text-muted">{s.expect}</span>
            </div>
            <p className="mt-0.5 text-sm text-ink-2">{s.text}</p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <button onClick={() => fwd.mutate(s.id)} disabled={fwd.isPending}
                className="min-h-9 rounded-lg bg-black px-3 text-xs font-medium text-white disabled:opacity-50">
                Forward to Lifeline
              </button>
              {results[s.id] && <OutcomeChip outcome={results[s.id].outcome} />}
            </div>
          </li>
        ))}
      </ul>
    </PhoneFrame>
  )
}

// --- Gmail sample inbox -------------------------------------------------------------------------
export function SampleInbox({ items }: { items: SyncItem[] | null }) {
  const inbox = useQuery({ queryKey: ['inbox'], queryFn: () => api<InboxMail[]>('/demo/inbox') })
  const bySubject = Object.fromEntries((items ?? []).map((i) => [i.subject, i]))
  return (
    <div className="overflow-hidden rounded-xl border border-line">
      <div className="flex items-center justify-between bg-surface px-3 py-2 text-xs font-semibold text-ink-2">
        <span>Sample inbox · {inbox.data?.length ?? 0} emails</span>
        {items && <Link to="/inbox" className="underline">Open Review →</Link>}
      </div>
      <ul className="divide-y divide-line bg-card">
        {inbox.data?.map((m) => {
          const r = bySubject[m.subject]
          return (
            <li key={m.id} className="px-3 py-2.5">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="text-sm font-semibold">{m.from}</span>
                <span className="truncate text-xs text-muted">&lt;{m.address}&gt;</span>
              </div>
              <div className="text-sm">{m.subject}</div>
              <div className="truncate text-xs text-muted">{m.preview}</div>
              <div className="mt-1">{r ? <OutcomeChip outcome={r.outcome} /> : <span className="text-xs text-muted">not read yet</span>}</div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
