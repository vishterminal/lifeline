import { useQuery } from '@tanstack/react-query'
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

function GoogleIcon() {
  return (
    <svg viewBox="0 0 48 48" className="h-5 w-5" aria-hidden="true">
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3 0 5.8 1.1 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.6-.4-3.5z" />
      <path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3 0 5.8 1.1 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.6-.4-3.5z" />
    </svg>
  )
}

export default function Login() {
  const [params] = useSearchParams()
  const nav = useNavigate()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [err, setErr] = useState<string | null>(ERRORS[params.get('error') ?? ''] ?? null)
  const [busy, setBusy] = useState(false)
  const health = useQuery({
    queryKey: ['health'],
    queryFn: () => api<{ connectors: Record<string, string> }>('/health'),
  })
  const googleMock = health.data?.connectors.google_login === 'mock'

  async function enterJudgeDemo() {
    setErr(null)
    setBusy(true)
    try {
      const r = await api<{ token: string; user: User }>('/auth/demo', { method: 'POST' })
      auth.set(r.token)
      nav('/overview')
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Could not reach the server. Is the backend running on port 8000?')
    } finally {
      setBusy(false)
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setErr(null)
    setBusy(true)
    try {
      const path = mode === 'login' ? '/auth/login' : '/auth/register'
      const body = mode === 'login' ? { email, password } : { email, password, name: name || undefined }
      const r = await api<{ token: string; user: User }>(path, { method: 'POST', json: body })
      auth.set(r.token)
      nav(mode === 'register' ? '/connect' : '/overview')
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Could not reach the server. Is the backend running on port 8000?')
    } finally {
      setBusy(false)
    }
  }

  const input = 'w-full ' + inputCls

  return (
    <div className="min-h-screen bg-bg">
      <div className="mx-auto grid min-h-screen max-w-6xl items-center gap-10 px-4 py-10 sm:px-6 lg:grid-cols-2">
        <div className="hidden lg:block">
          <Logo />
          <h1 className="mt-10 text-5xl font-extrabold leading-[1.05] tracking-tight text-ink">
            Every bill, renewal and due —<br /><span className="text-gold">in one place.</span>
          </h1>
          <p className="mt-5 max-w-md text-lg text-ink-2">
            Lifeline collects bills from Gmail, WhatsApp and SMS automatically, checks the sender is genuine,
            and tells you what needs you — before a late fee does.
          </p>
          <ul className="mt-8 space-y-3 text-ink-2">
            {[
              ['✉️', 'Reads only bill-like email, read-only'],
              ['🛡️', 'Blocks fake and phishing bills'],
              ['🔒', 'Stores extracted details — never your messages'],
            ].map(([i, t]) => (
              <li key={t} className="flex items-center gap-3">
                <span className="grid h-9 w-9 place-items-center rounded-xl border border-line bg-card" aria-hidden="true">{i}</span>{t}
              </li>
            ))}
          </ul>
        </div>

        <div className="mx-auto w-full max-w-md">
          <div className="mb-6 lg:hidden"><Logo /></div>
          <button onClick={enterJudgeDemo} disabled={busy}
            className="mb-2 flex min-h-12 w-full items-center justify-center gap-2 rounded-2xl bg-gold px-4 py-3 font-semibold text-bg shadow-[0_12px_30px_-12px_rgb(255_209_0/0.8)] hover:bg-gold-2 disabled:opacity-60">
            🎓 Enter judge demo — no sign-up
          </button>
          <p className="mb-4 text-center text-xs text-muted">For judges: a private demo account with sample Gmail, WhatsApp &amp; SMS. Real users sign in with Google below.</p>
          <div className="rounded-[var(--radius-card)] border border-line bg-card p-6 shadow-[var(--shadow-card)] sm:p-8">
            <h2 className="text-2xl font-bold tracking-tight">{mode === 'login' ? 'Welcome back' : 'Create your account'}</h2>
            <p className="mt-1 text-sm text-muted">{mode === 'login' ? 'Sign in to see what needs you.' : 'Takes a minute. Sources can be connected next.'}</p>
            <a
              href="/api/auth/google/start"
              className="mt-6 flex min-h-11 w-full items-center justify-center gap-3 rounded-xl border border-line-strong bg-surface px-4 py-2.5 font-medium text-ink hover:border-gold/50 hover:bg-raised"
            >
              <GoogleIcon /> Continue with Google
            </a>
            {googleMock && (
              <p className="mt-2 text-xs text-muted">
                Judge mode: Google keys aren't set, so this signs you in as a demo Google user. With keys it opens the
                real Google account picker — <a href="/proof" className="text-gold underline">see it live</a>.
              </p>
            )}

            <div className="my-6 flex items-center gap-3 text-xs text-muted">
              <div className="h-px flex-1 bg-line" /> or with email <div className="h-px flex-1 bg-line" />
            </div>

            <form onSubmit={submit} className="space-y-4">
              {mode === 'register' && (
                <label className="block">
                  <span className="text-sm font-medium text-ink-2">Name</span>
                  <input className={`${input} mt-1`} value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
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
              <button disabled={busy} className="min-h-11 w-full rounded-xl bg-gold px-4 py-2.5 font-semibold text-bg hover:bg-gold-2 disabled:opacity-60">
                {busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
              </button>
            </form>
            <button
              className="mt-4 w-full text-sm text-ink-2 hover:text-gold"
              onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setErr(null) }}
            >
              {mode === 'login' ? 'New here? Create an account' : 'Already have an account? Sign in'}
            </button>
          </div>
          <p className="mt-4 text-center text-xs text-muted"><a href="/proof" className="hover:text-gold">See Lifeline working with real Gmail →</a></p>
        </div>
      </div>
    </div>
  )
}
