// Phone-style simulators used in judge mode. They call the same pipeline the
// live Twilio / SMS-forwarder webhooks call.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  api, type Confirmation, type Fixtures, type InboxMail, type PipelineResult, type SyncItem, type User,
} from './api'
import { invalidateAll } from './judge'
import { OUTCOME_TEXT, outcomeTone } from './ui'

const TONE: Record<string, string> = {
  ok: 'border-emerald-400/30 bg-emerald-500/12 text-emerald-300', warn: 'border-amber-400/30 bg-amber-500/12 text-amber-300',
  error: 'border-red-400/30 bg-red-500/12 text-red-300', info: 'border-white/10 bg-white/5 text-ink-2',
}

export function OutcomeChip({ outcome }: { outcome: string }) {
  return (
    <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold ${TONE[outcomeTone(outcome)]}`}>
      {OUTCOME_TEXT[outcome] ?? outcome}
    </span>
  )
}

// ---- Realistic phone shell -----------------------------------------------------------------
function StatusBar() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => { const t = setInterval(() => setNow(new Date()), 30_000); return () => clearInterval(t) }, [])
  return (
    <div className="relative flex h-11 items-center justify-between px-7 text-[13px] font-semibold text-white">
      <span className="num">{now.toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit', hour12: false })}</span>
      <span className="absolute left-1/2 top-2.5 h-[26px] w-[92px] -translate-x-1/2 rounded-full bg-black" aria-hidden="true" />
      <span className="flex items-center gap-1.5" aria-hidden="true">
        <svg viewBox="0 0 18 12" className="h-3 w-[18px]" fill="currentColor"><rect x="0" y="8" width="3" height="4" rx="1" /><rect x="5" y="5.5" width="3" height="6.5" rx="1" /><rect x="10" y="3" width="3" height="9" rx="1" /><rect x="15" y="0" width="3" height="12" rx="1" /></svg>
        <svg viewBox="0 0 16 12" className="h-3 w-4" fill="currentColor"><path d="M8 11.5 5.6 9a3.4 3.4 0 0 1 4.8 0L8 11.5zM3.2 6.6l-1.6-1.6a9 9 0 0 1 12.8 0l-1.6 1.6a6.8 6.8 0 0 0-9.6 0z" /></svg>
        <span className="relative inline-flex h-[12px] w-[25px] items-center rounded-[4px] border border-white/60 p-[1.5px]">
          <span className="h-full w-[75%] rounded-[2px] bg-white" /><span className="absolute -right-[3px] h-1 w-[2px] rounded-r bg-white/60" />
        </span>
      </span>
    </div>
  )
}

function Phone({ children, notice }: { children: React.ReactNode; notice?: React.ReactNode }) {
  return (
    <div className="relative mx-auto w-full max-w-[320px]">
      <span className="absolute -left-[3px] top-28 h-8 w-[3px] rounded-l bg-[#3a3a3c]" aria-hidden="true" />
      <span className="absolute -left-[3px] top-40 h-14 w-[3px] rounded-l bg-[#3a3a3c]" aria-hidden="true" />
      <span className="absolute -left-[3px] top-[15.5rem] h-14 w-[3px] rounded-l bg-[#3a3a3c]" aria-hidden="true" />
      <span className="absolute -right-[3px] top-44 h-20 w-[3px] rounded-r bg-[#3a3a3c]" aria-hidden="true" />
      <div className="rounded-[3.1rem] bg-gradient-to-b from-[#4a4a4e] via-[#2c2c2e] to-[#1c1c1e] p-[3px] shadow-[0_30px_60px_-25px_rgb(0_0_0/0.9),0_0_0_1px_rgb(255_255_255/0.06)]">
        <div className="rounded-[2.95rem] bg-black p-[9px]">
          <div className="relative flex h-[600px] flex-col overflow-hidden rounded-[2.5rem] bg-[#0b141a]">
            {children}
            {notice && <div className="pointer-events-none absolute inset-x-2 top-12 z-10 animate-drop-in">{notice}</div>}
            <span className="absolute bottom-2 left-1/2 h-[5px] w-32 -translate-x-1/2 rounded-full bg-white/70" aria-hidden="true" />
          </div>
        </div>
      </div>
    </div>
  )
}

function PushNotice({ title, text }: { title: string; text: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-[#1f1f1f]/95 p-3 text-white shadow-2xl backdrop-blur-xl">
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-white/60">
        <span className="grid h-5 w-5 place-items-center rounded-md bg-gold text-[10px] font-black text-bg">L</span>{title}<span className="ml-auto normal-case">now</span>
      </div>
      <div className="mt-1 text-sm leading-snug">{text}</div>
    </div>
  )
}

function useFlash<T>() {
  const [v, setV] = useState<T | null>(null)
  useEffect(() => { if (v) { const t = setTimeout(() => setV(null), 3500); return () => clearTimeout(t) } }, [v])
  return [v, setV] as const
}

// ---- WhatsApp -------------------------------------------------------------------------------------
type Msg = { from: 'me' | 'bot'; text: string; at: string }
const stamp = () => new Date().toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit', hour12: false })

export function WhatsAppSimulator() {
  const qc = useQueryClient()
  const fx = useQuery({ queryKey: ['fixtures'], queryFn: () => api<Fixtures>('/demo/fixtures') })
  const [msgs, setMsgs] = useState<Msg[]>([
    { from: 'bot', text: "Hi! Forward me any bill, renewal notice or receipt and I'll track it. Send HELP for commands.", at: stamp() },
  ])
  const [text, setText] = useState('')
  const send = useMutation({
    mutationFn: (t: string) => api<{ reply: string }>('/demo/simulate/whatsapp', { method: 'POST', json: { text: t } }),
    onMutate: (t) => setMsgs((m) => [...m, { from: 'me', text: t, at: stamp() }]),
    onSuccess: (r) => { setMsgs((m) => [...m, { from: 'bot', text: r.reply, at: stamp() }]); invalidateAll(qc) },
    onError: (e) => setMsgs((m) => [...m, { from: 'bot', text: `⚠ ${(e as Error).message}`, at: stamp() }]),
  })
  const submit = (t: string) => { if (t.trim() && !send.isPending) { send.mutate(t.trim()); setText('') } }
  useEffect(() => {
    const el = document.getElementById('wa-scroll')
    if (el) el.scrollTop = el.scrollHeight
  }, [msgs.length, send.isPending])

  return (
    <Phone>
      <div className="bg-[#1f2c34]"><StatusBar /></div>
      <div className="flex items-center gap-3 bg-[#1f2c34] px-3 pb-2.5 text-[#e9edef]">
        <svg viewBox="0 0 24 24" className="h-5 w-5 text-[#aebac1]" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M15 18l-6-6 6-6" /></svg>
        <span className="grid h-9 w-9 place-items-center rounded-full bg-gold text-sm font-black text-bg">L</span>
        <div className="min-w-0 flex-1">
          <div className="text-[15px] font-semibold leading-tight">Lifeline</div>
          <div className="text-xs text-[#8696a0]">{send.isPending ? 'typing…' : 'online'}</div>
        </div>
      </div>
      <div id="wa-scroll" className="flex-1 space-y-1.5 overflow-y-auto bg-[#0b141a] bg-[radial-gradient(rgb(255_255_255/0.035)_1px,transparent_1px)] bg-[length:18px_18px] px-3 py-3" aria-live="polite">
        <div className="mx-auto mb-2 w-fit rounded-md bg-[#182229] px-2 py-0.5 text-[11px] text-[#8696a0]">TODAY</div>
        {msgs.map((m, i) => (
          <div key={i} className={`flex ${m.from === 'me' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[82%] whitespace-pre-line rounded-lg px-2.5 pb-1 pt-1.5 text-[13.5px] leading-snug text-[#e9edef] shadow ${m.from === 'me' ? 'rounded-tr-none bg-[#005c4b]' : 'rounded-tl-none bg-[#202c33]'}`}>
              {m.text}
              <span className="float-right ml-2 mt-1 text-[10px] text-[#8696a0]">{m.at}{m.from === 'me' && <span className="ml-1 text-[#53bdeb]">✓✓</span>}</span>
            </div>
          </div>
        ))}
      </div>
      <div className="flex gap-1.5 overflow-x-auto bg-[#0b141a] px-2 pb-1.5">
        {fx.data?.whatsapp.map((f) => (
          <button key={f.id} onClick={() => submit(f.text)} disabled={send.isPending}
            className="shrink-0 rounded-full border border-[#00a884]/40 bg-[#00a884]/10 px-2.5 py-1 text-xs text-[#7fe0c8] hover:bg-[#00a884]/20 disabled:opacity-50">
            {f.id === 'bill' ? '↪ Forward TNEB bill' : f.id === 'puc' ? '↪ Forward PUC notice' : f.text}
          </button>
        ))}
      </div>
      <form className="flex items-center gap-2 bg-[#0b141a] px-2 pb-6 pt-1" onSubmit={(e) => { e.preventDefault(); submit(text) }}>
        <label htmlFor="wa-sim" className="sr-only">Message</label>
        <input id="wa-sim" value={text} onChange={(e) => setText(e.target.value)} placeholder="Message"
          className="min-h-10 flex-1 rounded-full bg-[#2a3942] px-4 text-sm text-[#e9edef] placeholder:text-[#8696a0] focus:outline-none" />
        <button aria-label="Send" className="grid h-10 w-10 place-items-center rounded-full bg-[#00a884] text-[#0b141a] disabled:opacity-50" disabled={send.isPending || !text.trim()}>
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="currentColor" aria-hidden="true"><path d="M3 20l18-8L3 4v6l12 2-12 2z" /></svg>
        </button>
      </form>
    </Phone>
  )
}

// ---- SMS (Android Messages style) --------------------------------------------------------------------
type Forwarded = Record<string, { outcome: string; confirmation_id?: string }>
const AV = ['#6d8cff', '#ff8a65', '#4db6ac', '#ba68c8', '#ffb74d', '#81c784']

function storeKey(uid?: string) { return uid ? `lifeline.sms.${uid}` : '' }
function loadForwarded(uid?: string): Forwarded {
  if (!uid) return {}
  try { return JSON.parse(localStorage.getItem(storeKey(uid)) || '{}') } catch { return {} }
}

export function SmsSimulator() {
  const qc = useQueryClient()
  const me = useQuery({ queryKey: ['me'], queryFn: () => api<{ user: User }>('/auth/me') })
  const uid = me.data?.user.id
  const fx = useQuery({ queryKey: ['fixtures'], queryFn: () => api<Fixtures>('/demo/fixtures') })
  const confs = useQuery({ queryKey: ['confirmations'], queryFn: () => api<Confirmation[]>('/confirmations') })
  const [fwd, setFwd] = useState<Forwarded>({})
  const [flash, setFlash] = useFlash<{ title: string; text: string }>()
  useEffect(() => { setFwd(loadForwarded(uid)) }, [uid])
  const save = (next: Forwarded) => {
    setFwd(next)
    try { if (uid) localStorage.setItem(storeKey(uid), JSON.stringify(next)) } catch { /* private mode */ }
  }

  const forward = useMutation({
    mutationFn: (id: string) => api<PipelineResult & { confirmation_id?: string }>('/demo/simulate/sms', { method: 'POST', json: { fixture: id } }),
    onSuccess: (r, id) => {
      save({ ...fwd, [id]: { outcome: r.outcome, confirmation_id: r.confirmation_id } })
      setFlash({ title: 'Lifeline', text: OUTCOME_TEXT[r.outcome] ?? r.outcome })
      invalidateAll(qc)
    },
    onError: (e) => setFlash({ title: 'Lifeline', text: `⚠ ${(e as Error).message}` }),
  })
  const pendingIds = useMemo(() => new Set((confs.data ?? []).map((c) => c.id)), [confs.data])
  // A forwarded SMS leaves the phone once it's handled: right away if nothing needs you,
  // or as soon as you've confirmed or rejected it in Review.
  const isDone = (id: string) => {
    const f = fwd[id]
    if (!f) return false
    if (f.outcome !== 'NEEDS_CONFIRMATION') return true
    return !!f.confirmation_id && confs.isSuccess && !pendingIds.has(f.confirmation_id)
  }
  const all = fx.data?.sms ?? []
  const inbox = all.filter((s) => !isDone(s.id))
  const handled = all.length - inbox.length

  return (
    <Phone notice={flash && <PushNotice title={flash.title} text={flash.text} />}>
      <div className="bg-[#121212]"><StatusBar /></div>
      <div className="bg-[#121212] px-4 pb-3 text-white">
        <div className="text-[22px] font-semibold tracking-tight">Messages</div>
        <div className="mt-2 flex items-center gap-2 rounded-full bg-[#2a2a2a] px-3 py-2 text-sm text-white/50">
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
          Search conversations
        </div>
      </div>
      <ul className="flex-1 overflow-y-auto bg-[#121212] pb-10">
        {inbox.map((s, i) => {
          const f = fwd[s.id]
          return (
            <li key={s.id} className="border-t border-white/5 px-4 py-3 transition-colors hover:bg-white/[0.04]">
              <div className="flex gap-3">
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full text-sm font-bold text-black" style={{ background: AV[i % AV.length] }} aria-hidden="true">
                  {s.sender.replace(/^[A-Z]{2}-/, '').replace('+', '').slice(0, 1)}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="truncate text-[14px] font-semibold text-white">{s.sender}</span>
                    <span className="shrink-0 text-[11px] text-white/40">{i === 0 ? 'now' : `${i * 7}m`}</span>
                  </div>
                  <p className="text-[13px] leading-snug text-white/70">{s.text}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    {!f ? (
                      <button onClick={() => forward.mutate(s.id)} disabled={forward.isPending}
                        className="rounded-full bg-gold px-3 py-1 text-xs font-semibold text-bg hover:bg-gold-2 disabled:opacity-50">
                        ↪ Forward to Lifeline
                      </button>
                    ) : (
                      <Link to="/inbox" className="rounded-full border border-amber-400/40 bg-amber-500/15 px-3 py-1 text-xs font-semibold text-amber-200 hover:bg-amber-500/25">
                        Waiting for your review →
                      </Link>
                    )}
                    <span className="text-[11px] text-white/35">{s.expect}</span>
                  </div>
                </div>
              </div>
            </li>
          )
        })}
        {inbox.length === 0 && fx.isSuccess && (
          <li className="grid place-items-center px-6 py-16 text-center text-white/60">
            <div className="text-3xl" aria-hidden="true">✓</div>
            <div className="mt-2 font-semibold text-white">All caught up</div>
            <div className="text-sm">Every message has been handled. Use “Reset demo” to replay.</div>
          </li>
        )}
      </ul>
      {handled > 0 && <div className="absolute inset-x-0 bottom-5 text-center text-[11px] text-white/40">{handled} handled by Lifeline</div>}
    </Phone>
  )
}

export function clearSmsSimulatorState() {
  try { Object.keys(localStorage).filter((k) => k.startsWith('lifeline.sms.')).forEach((k) => localStorage.removeItem(k)) } catch { /* ignore */ }
}

// ---- Gmail sample inbox -------------------------------------------------------------------------------
export function SampleInbox({ items, synced = false }: { items: SyncItem[] | null; synced?: boolean }) {
  const inbox = useQuery({ queryKey: ['inbox'], queryFn: () => api<InboxMail[]>('/demo/inbox') })
  const bySubject = Object.fromEntries((items ?? []).map((i) => [i.subject, i]))
  return (
    <div className="glass-inner overflow-hidden rounded-2xl">
      <div className="flex items-center justify-between border-b border-white/10 px-4 py-2.5 text-xs font-semibold uppercase tracking-wider text-muted">
        <span>✉️ Sample inbox · {inbox.data?.length ?? 0} emails</span>
        {(items || synced) && <Link to="/inbox" className="normal-case tracking-normal text-gold hover:underline">Open Review →</Link>}
      </div>
      <ul className="divide-y divide-white/[0.07]">
        {inbox.data?.map((m) => {
          const r = bySubject[m.subject]
          return (
            <li key={m.id} className="row-hover px-4 py-3">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="text-sm font-semibold text-ink">{m.from}</span>
                <span className="truncate text-xs text-muted">&lt;{m.address}&gt;</span>
              </div>
              <div className="text-sm text-ink">{m.subject}</div>
              <div className="truncate text-xs text-muted">{m.preview}</div>
              <div className="mt-1.5">{r ? <OutcomeChip outcome={r.outcome} /> : <span className="text-xs text-muted">{synced ? '✓ processed — see Review & Bills' : 'unread'}</span>}</div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
