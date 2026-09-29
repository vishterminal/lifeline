import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api } from './api'

type Turn = { who: 'me' | 'bot'; text: string }

/** Floating "Ask Lifeline" chat — answers from the user's own bills. */
export default function AskLifeline() {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [turns, setTurns] = useState<Turn[]>([{ who: 'bot', text: 'Hi! Ask me anything about your bills — what’s due, what’s urgent, or whether you can afford it before salary.' }])
  const sug = useQuery({ queryKey: ['ask-sug'], queryFn: () => api<string[]>('/ask/suggestions'), enabled: open, staleTime: Infinity })
  const end = useRef<HTMLDivElement>(null)
  const ask = useMutation({
    mutationFn: (question: string) => api<{ answer: string }>('/ask', { method: 'POST', json: { question } }),
    onMutate: (question) => setTurns((t) => [...t, { who: 'me', text: question }]),
    onSuccess: (r) => setTurns((t) => [...t, { who: 'bot', text: r.answer }]),
    onError: () => setTurns((t) => [...t, { who: 'bot', text: 'Sorry, something went wrong. Try again.' }]),
  })
  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }) }, [turns.length, ask.isPending])
  const send = (text: string) => { const v = text.trim(); if (v && !ask.isPending) { ask.mutate(v); setQ('') } }

  return (
    <>
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-label="Ask Lifeline"
        className="fixed bottom-5 right-5 z-30 inline-flex print:hidden min-h-12 items-center gap-2 rounded-full bg-gold px-5 font-semibold text-bg shadow-[0_14px_34px_-10px_rgb(255_209_0/0.8)] hover:bg-gold-2"
        style={{ bottom: 'calc(1.25rem + env(safe-area-inset-bottom, 0px))' }}>
        {open ? '✕ Close' : '💬 Ask Lifeline'}
      </button>
      {open && (
        <div role="dialog" aria-label="Ask Lifeline"
          className="fixed bottom-24 right-5 z-30 flex max-h-[70vh] border border-line-strong bg-surface shadow-[0_30px_60px_-20px_rgb(0_0_0/0.9)] w-[min(24rem,calc(100vw-2.5rem))] flex-col overflow-hidden rounded-[var(--radius-card)]">
          <div className="border-b border-white/10 px-4 py-3"><b className="text-gold">Ask Lifeline</b><div className="text-xs text-muted">Answers come from your own bills — exact numbers, no guessing.</div></div>
          <div className="flex-1 space-y-2 overflow-y-auto p-3" aria-live="polite">
            {turns.map((t, i) => (
              <div key={i} className={`flex ${t.who === 'me' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[88%] whitespace-pre-line rounded-2xl px-3 py-2 text-sm ${t.who === 'me' ? 'bg-gold text-bg' : 'bg-card border border-line text-ink'}`}>{t.text}</div>
              </div>
            ))}
            {ask.isPending && <div className="text-xs text-muted">Thinking…</div>}
            <div ref={end} />
          </div>
          <div className="flex flex-wrap gap-1.5 px-3 pb-2">
            {(sug.data ?? []).slice(0, 4).map((s) => (
              <button key={s} onClick={() => send(s)} className="rounded-full border border-gold/30 bg-gold/10 px-2.5 py-1 text-xs text-gold hover:bg-gold/20">{s}</button>
            ))}
          </div>
          <form className="flex gap-2 border-t border-white/10 p-3" onSubmit={(e) => { e.preventDefault(); send(q) }}>
            <label htmlFor="ask-input" className="sr-only">Your question</label>
            <input id="ask-input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. What do I owe this week?"
              className="min-h-11 flex-1 rounded-xl border border-line-strong bg-surface px-3 text-sm text-ink placeholder:text-muted focus:border-gold/60 focus:outline-none" />
            <button className="min-h-11 rounded-xl bg-gold px-4 text-sm font-semibold text-bg disabled:opacity-50" disabled={ask.isPending || !q.trim()}>Ask</button>
          </form>
        </div>
      )}
    </>
  )
}
