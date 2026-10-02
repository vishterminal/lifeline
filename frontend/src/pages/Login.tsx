import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError, auth, type User } from '../api'
import { inputCls, Logo, Notice } from '../ui'

const ERRORS: Record<string, string> = {
  google_cancelled: 'Google sign-in was cancelled.',
  state_mismatch: 'Sign-in expired. Please try again.',
  email_not_verified: 'Your Google email is not verified.',
  google_token_error: 'Google sign-in failed. Check the Google keys in .env.',
  google_userinfo_error: 'Could not read your Google profile.',
  google_unreachable: 'Could not reach Google. Check your connection.',
}


function Preview() {
  return (
    <div className="relative mt-10 hidden max-w-lg lg:block" aria-hidden="true">
      <div className="absolute -inset-6 rounded-[2rem] bg-gold/10 blur-3xl" />
      <div className="glass relative rounded-[var(--radius-card)] p-5">
        <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-muted">
          <span>Bills · ranked by ₹ risk</span><span className="text-gold">Live preview</span>
        </div>
        <div className="glass-inner mt-3 rounded-2xl p-4">
          <div className="flex items-start gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-surface text-lg">🚘</span>
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-2"><b>PUC certificate</b><span className="num text-sm font-bold text-gold">₹7,000 at risk</span></div>
              <div className="text-xs text-muted">Expires in 5 days</div>
              <div className="mt-2 rounded-lg border border-amber-400/25 bg-amber-500/10 px-2.5 py-1.5 text-xs text-amber-200">⛓ Insurance renewal will be blocked without it</div>
            </div>
          </div>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-3">
          <div className="glass-inner rounded-2xl p-3">
            <div className="text-xs text-muted">Blocked</div>
            <div className="mt-0.5 text-sm font-semibold text-red-300">⚠ Fake “Netflix” bill</div>
            <div className="text-[11px] text-muted">look-alike domain · DMARC fail</div>
          </div>
          <div className="glass-inner rounded-2xl p-3">
            <div className="text-xs text-muted">Arrived by</div>
            <div className="mt-0.5 text-sm font-semibold">✉️ 💬 📱 → shown once</div>
            <div className="text-[11px] text-muted">Gmail · WhatsApp · SMS</div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function Login() {
  const [params] = useSearchParams()
  const nav = useNavigate()
  const [mode, setMode] = useState<'register' | 'login'>(params.get('mode') === 'signin' ? 'login' : 'register')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [err, setErr] = useState<string | null>(ERRORS[params.get('error') ?? ''] ?? null)
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setErr(null)
    setBusy(true)
    try {
      const path = mode === 'login' ? '/auth/login' : '/auth/register'
      const body = mode === 'login' ? { email, password } : { email, password, name: name || undefined }
      const r = await api<{ token: string; user: User }>(path, { method: 'POST', json: body })
      auth.set(r.token)
      nav('/connect') // next step: connect your own Gmail, WhatsApp and SMS
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Could not reach the server. Is the backend running on port 8000?')
    } finally {
      setBusy(false)
    }
  }

  const input = 'w-full ' + inputCls

  return (
    <div className="min-h-screen">
      <div className="mx-auto grid min-h-screen max-w-6xl items-center gap-12 px-4 py-10 sm:px-6 lg:grid-cols-[1.1fr_1fr] [&>*]:min-w-0">
        <div>
          <Logo />
          <span className="mt-8 inline-flex items-center gap-2 rounded-full border border-gold/30 bg-gold/10 px-3 py-1 text-xs font-semibold text-gold">
            ● Bills · renewals · dues — on autopilot
          </span>
          <h1 className="mt-4 text-4xl font-extrabold leading-[1.05] tracking-tight text-ink sm:text-5xl lg:text-6xl">
            Track everything.<br /><span className="bg-gradient-to-r from-gold to-gold-2 bg-clip-text text-transparent">Miss nothing.</span>
          </h1>
          <p className="mt-5 max-w-xl text-lg text-ink-2">
            Lifeline reads your bills from Gmail, WhatsApp and SMS, checks the sender is genuine,
            and ranks what you owe by what missing it would really cost — before a late fee does.
          </p>
          <ul className="mt-6 flex flex-wrap gap-2 text-sm">
            {['✉️ Read-only Gmail', '🛡️ Blocks phishing bills', '₹ Ranked by real risk', '🔒 Never stores your messages'].map((t) => (
              <li key={t} className="glass rounded-full px-3 py-1.5 text-ink-2">{t}</li>
            ))}
          </ul>
          <Preview />
        </div>

        <div className="mx-auto w-full max-w-md">
          <div className="glass rounded-[var(--radius-card)] p-6 sm:p-8">
            <h2 className="text-2xl font-bold tracking-tight">{mode === 'register' ? 'Create new account' : 'Sign in'}</h2>
            <p className="mt-1 text-sm text-muted">
              {mode === 'register'
                ? 'Takes 20 seconds. Next you connect your own Gmail, WhatsApp and SMS, and your bills start arriving.'
                : 'Pick up where you left off.'}
            </p>

            <form onSubmit={submit} className="mt-6 space-y-4">
              {mode === 'register' && (
                <label className="block">
                  <span className="text-sm font-medium text-ink-2">Full name</span>
                  <input className={`${input} mt-1`} value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" required />
                </label>
              )}
              <label className="block">
                <span className="text-sm font-medium text-ink-2">Email</span>
                <input className={`${input} mt-1`} type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
              </label>
              <label className="block">
                <span className="text-sm font-medium text-ink-2">Password</span>
                <input className={`${input} mt-1`} type="password" required minLength={8} value={password}
                  onChange={(e) => setPassword(e.target.value)} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} />
                {mode === 'register' && <span className="text-xs text-muted">At least 8 characters</span>}
              </label>
              {err && <Notice tone="error">{err}</Notice>}
              <button disabled={busy} className="min-h-12 w-full rounded-xl bg-gold px-4 py-3 font-semibold text-bg shadow-[0_12px_30px_-12px_rgb(255_209_0/0.8)] hover:bg-gold-2 disabled:opacity-60">
                {busy ? 'Please wait…' : mode === 'register' ? 'Create account' : 'Sign in'}
              </button>
            </form>

            <p className="mt-6 text-center text-sm text-ink-2">
              {mode === 'register'
                ? <>Already have an account? <button className="font-semibold text-gold hover:underline" onClick={() => { setMode('login'); setErr(null) }}>Sign in</button></>
                : <>New here? <button className="font-semibold text-gold hover:underline" onClick={() => { setMode('register'); setErr(null) }}>Create new account</button></>}
            </p>
          </div>
          <p className="mt-4 text-center text-xs text-muted"><a href="/proof" className="hover:text-gold">See Lifeline working with a real Gmail inbox →</a></p>
        </div>
      </div>
    </div>
  )
}
