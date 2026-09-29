// Judge mode: when the app runs without Google/Twilio keys (e.g. cloned from
// GitHub), every source runs on realistic sample messages through the REAL
// pipeline. These components make that obvious and easy to try.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, type Health, type SyncResult } from './api'
import { Button } from './ui'

export function useHealth() {
  return useQuery({ queryKey: ['health'], queryFn: () => api<Health>('/health'), staleTime: 60_000 })
}

export function useJudgeMode() {
  return useHealth().data?.judge_mode ?? false
}

export function invalidateAll(qc: ReturnType<typeof useQueryClient>) {
  ;['sources', 'confirmations', 'flagged', 'obligations', 'events', 'me', 'inbox'].forEach((k) =>
    qc.invalidateQueries({ queryKey: [k] }))
}

/** One-click walkthrough of every input channel. */
export async function runFullDemo(step: (msg: string) => void) {
  step('Connecting the sample Gmail inbox…')
  const { auth_url } = await api<{ auth_url: string }>('/sources/gmail/connect')
  await fetch(auth_url, { redirect: 'manual', credentials: 'include' })
  step('Reading bill-like emails (7 in the sample inbox)…')
  const sync = await api<SyncResult>('/sources/gmail/sync', { method: 'POST' })
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

export function JudgeBanner() {
  const judge = useJudgeMode()
  const qc = useQueryClient()
  const nav = useNavigate()
  const [log, setLog] = useState<string[]>([])
  const [open, setOpen] = useState(false)
  const run = useMutation({
    mutationFn: () => { setLog([]); setOpen(true); return runFullDemo((m) => setLog((l) => [...l, m])) },
    onSettled: () => invalidateAll(qc),
    onError: (e) => setLog((l) => [...l, `Error: ${(e as Error).message}`]),
  })
  const reset = useMutation({
    mutationFn: () => api('/demo', { method: 'DELETE' }),
    onSuccess: () => { invalidateAll(qc); setLog([]); setOpen(false) },
  })
  if (!judge) return null
  return (
    <div className="border-b border-gold/20 bg-gradient-to-r from-gold/10 via-surface to-surface">
      <div className="mx-auto max-w-5xl px-4 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="min-w-0 flex-1 text-sm text-ink-2">
            <b className="text-gold">🎓 Judge demo mode.</b> No Google/Twilio keys are configured, so Gmail, WhatsApp and SMS run on
            realistic sample messages through the <b>real</b> pipeline. With keys in <code>.env</code> the same
            screens connect a live Gmail inbox, WhatsApp number and SMS forwarder —{' '}
            <Link to="/proof" className="font-semibold text-gold underline">see it working live</Link>.
          </div>
          <div className="flex gap-2">
            <Button onClick={() => run.mutate()} disabled={run.isPending}>{run.isPending ? 'Running…' : '▶ Run full demo'}</Button>
            <Button variant="secondary" onClick={() => reset.mutate()} disabled={reset.isPending}>Reset demo</Button>
          </div>
        </div>
        {open && log.length > 0 && (
          <div className="mt-3 rounded-2xl border border-line bg-card p-4 text-sm" aria-live="polite">
            <ol className="space-y-1">
              {log.map((m, i) => <li key={i}>{m === 'Done.' ? '✅' : '•'} {m}</li>)}
            </ol>
            {log.at(-1) === 'Done.' && (
              <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-3">
                <span>Next: confirm the TNEB bill (it arrived by 3 channels, shown once), then send the payment SMS.</span>
                <Button onClick={() => nav('/inbox')}>Open Review →</Button>
                <Button variant="ghost" onClick={() => setOpen(false)}>Close</Button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
