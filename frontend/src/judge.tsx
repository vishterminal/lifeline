// Judge mode: when the app runs without Google/Twilio keys (e.g. cloned from
// GitHub), every source runs on realistic sample messages through the REAL
// pipeline. These components make that obvious and easy to try.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, auth, type Health, type SyncResult, type User } from './api'
import { clearSmsSimulatorState } from './simulators'
import { Button } from './ui'

export function useHealth() {
  return useQuery({ queryKey: ['health'], queryFn: () => api<Health>('/health'), staleTime: 60_000 })
}

/** Judge mode = this is a judge demo account, or the server has no live keys at all. */
export function useJudgeMode() {
  const health = useHealth()
  const me = useQuery({ queryKey: ['me'], queryFn: () => api<{ user: User }>('/auth/me'), enabled: !!auth.get() })
  return (health.data?.judge_mode ?? false) || (me.data?.user.is_demo ?? false)
}

export function invalidateAll(qc: ReturnType<typeof useQueryClient>) {
  ;['sources', 'confirmations', 'flagged', 'obligations', 'bills', 'events', 'me', 'inbox', 'sms-status'].forEach((k) =>
    qc.invalidateQueries({ queryKey: [k] }))
}

/** One-click walkthrough of every input channel. */
export async function runFullDemo(step: (msg: string) => void) {
  step('Connecting the sample Gmail inbox…')
  const { auth_url } = await api<{ auth_url: string }>('/sources/gmail/connect')
  await fetch(auth_url, { redirect: 'manual', credentials: 'include' })
  step('Reading bill-like emails (7 in the sample inbox)…')
  const sync = await api<SyncResult>('/sources/gmail/sync', { method: 'POST' })
  if (sync.fetched === 0 || (sync.items ?? []).every((i) => i.outcome === 'DUPLICATE')) {
    step('Everything here was already processed (duplicates are skipped on purpose). Press "Reset demo" to replay from scratch.')
    step('Done.')
    return
  }
  step(`Gmail: ${sync.fetched} read · ${sync.needs_review} to review · ${sync.flagged} phishing flagged`)
  step('WhatsApp: forwarding the same TNEB bill…')
  await api('/demo/simulate/whatsapp', { method: 'POST', json: { fixture: 'bill' } })
  step('SMS: the same TNEB bill arrives by SMS too…')
  await api('/demo/simulate/sms', { method: 'POST', json: { fixture: 'bill' } })
  step('SMS: an OTP arrives (must be dropped, nothing stored)…')
  await api('/demo/simulate/sms', { method: 'POST', json: { fixture: 'otp' } })
  step('SMS: AI and rules read different amounts…')
  await api('/demo/simulate/sms', { method: 'POST', json: { fixture: 'mismatch' } })
  step('Done.')
}

function useDemoControls() {
  const qc = useQueryClient()
  const [log, setLog] = useState<string[]>([])
  const run = useMutation({
    mutationFn: () => { setLog([]); return runFullDemo((m) => setLog((l) => [...l, m])) },
    onSettled: () => invalidateAll(qc),
    onError: (e) => setLog((l) => [...l, `Error: ${(e as Error).message}`]),
  })
  const reset = useMutation({
    mutationFn: () => api('/demo', { method: 'DELETE' }),
    onSuccess: () => { clearSmsSimulatorState(); qc.removeQueries({ queryKey: ['whatif'] }); invalidateAll(qc); setLog(['Demo data cleared — everything can be replayed.']) },
  })
  return { log, setLog, run, reset }
}

function DemoLog({ log, onClose }: { log: string[]; onClose: () => void }) {
  const nav = useNavigate()
  if (log.length === 0) return null
  return (
    <div className="glass-inner mt-3 rounded-2xl p-4 text-sm" aria-live="polite">
      <ol className="space-y-1">{log.map((m, i) => <li key={i}>{m === 'Done.' ? '✅' : '•'} {m}</li>)}</ol>
      {log.at(-1) === 'Done.' && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-white/10 pt-3">
          <span className="text-ink-2">Next: confirm the TNEB bill in Review (it arrived by 3 channels, shown once), then forward the payment SMS.</span>
          <Button onClick={() => { onClose(); nav('/inbox') }}>Open Review →</Button>
        </div>
      )}
      <button className="mt-2 text-xs text-muted hover:text-ink" onClick={onClose}>Close</button>
    </div>
  )
}

/** Full explanation banner — shown on the Overview page only. */
export function JudgeBanner() {
  const judge = useJudgeMode()
  const { log, setLog, run, reset } = useDemoControls()
  if (!judge) return null
  return (
    <section className="glass mb-6 rounded-[var(--radius-card)] border-gold/25 p-5">
      <div className="flex flex-wrap items-center gap-4">
        <div className="min-w-0 flex-[1_1_20rem] text-sm text-ink-2">
          <b className="text-gold">🎓 Judge demo mode.</b> This is a private demo account: Gmail, WhatsApp and SMS run on
          realistic sample messages through the <b className="text-ink">real</b> pipeline. Real accounts (<i>Continue with Google</i>)
          connect a live Gmail inbox, WhatsApp number and SMS forwarder —{' '}
          <Link to="/proof" className="font-semibold text-gold underline">see it working live</Link>.
        </div>
        <div className="flex gap-2">
          <Button onClick={() => run.mutate()} disabled={run.isPending}>{run.isPending ? 'Running…' : '▶ Run full demo'}</Button>
          <Button variant="secondary" onClick={() => reset.mutate()} disabled={reset.isPending}>Reset demo</Button>
        </div>
      </div>
      <DemoLog log={log} onClose={() => setLog([])} />
    </section>
  )
}

/** Compact header control on every other page. */
export function DemoPill() {
  const judge = useJudgeMode()
  const [open, setOpen] = useState(false)
  const { log, setLog, run, reset } = useDemoControls()
  if (!judge) return null
  return (
    <div className="relative">
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="inline-flex min-h-11 items-center gap-1.5 whitespace-nowrap rounded-full border border-gold/40 bg-gold/10 px-3 text-sm font-semibold text-gold hover:bg-gold/20">
        🎓 <span className="hidden sm:inline">Judge demo</span>
      </button>
      {open && (
        <div className="glass absolute right-0 z-30 mt-2 w-80 rounded-2xl p-4 text-sm" role="dialog" aria-label="Judge demo controls">
          <p className="text-ink-2">Sample Gmail, WhatsApp &amp; SMS through the real pipeline.</p>
          <div className="mt-3 flex gap-2">
            <Button onClick={() => run.mutate()} disabled={run.isPending}>{run.isPending ? 'Running…' : '▶ Run full demo'}</Button>
            <Button variant="secondary" onClick={() => reset.mutate()} disabled={reset.isPending}>Reset</Button>
          </div>
          <DemoLog log={log} onClose={() => { setLog([]); setOpen(false) }} />
        </div>
      )}
    </div>
  )
}
