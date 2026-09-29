import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError, auth, type User } from '../api'

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

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setErr(null)
    setBusy(true)
    try {
      const path = mode === 'login' ? '/auth/login' : '/auth/register'
      const body = mode === 'login' ? { email, password } : { email, password, name: name || undefined }
      const r = await api<{ token: string; user: User }>(path, { method: 'POST', json: body })
      auth.set(r.token)
      nav(mode === 'register' ? '/connect' : '/inbox')
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Could not reach the server. Is the backend running on port 8000?')
    } finally {
      setBusy(false)
    }
  }

  const input = 'w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-slate-900'

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        <h1 className="text-3xl font-bold tracking-tight">Lifeline</h1>
        <p className="mt-1 text-slate-600">All your bills, renewals and dues in one place — collected automatically.</p>

        {googleMock && (
          <a href="/api/auth/google/start"
            className="mt-6 flex min-h-12 w-full items-center justify-center gap-2 rounded-2xl bg-violet-600 px-4 py-3 font-semibold text-white shadow-sm hover:bg-violet-700">
            🎓 Enter judge demo — no sign-up
          </a>
        )}
        <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <a
            href="/api/auth/google/start"
            className="flex min-h-11 w-full items-center justify-center gap-3 rounded-lg border border-slate-300 bg-white px-4 py-2.5 font-medium hover:bg-slate-50"
          >
            <GoogleIcon /> Continue with Google
          </a>
          {googleMock && (
            <p className="mt-2 text-xs text-violet-700">
              Judge mode: Google keys aren't set, so this signs you in as a demo Google user. With keys it opens the
              real Google account picker — <a href="/proof" className="underline">see it live</a>.
            </p>
          )}

          <div className="my-5 flex items-center gap-3 text-xs text-slate-400">
            <div className="h-px flex-1 bg-slate-200" /> or with email <div className="h-px flex-1 bg-slate-200" />
          </div>

          <form onSubmit={submit} className="space-y-3">
            {mode === 'register' && (
              <label className="block">
                <span className="text-sm font-medium">Name</span>
                <input className={input} value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
              </label>
            )}
            <label className="block">
              <span className="text-sm font-medium">Email</span>
              <input className={input} type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
            </label>
            <label className="block">
              <span className="text-sm font-medium">Password</span>
              <input className={input} type="password" required minLength={8} value={password}
                onChange={(e) => setPassword(e.target.value)} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} />
              {mode === 'register' && <span className="text-xs text-slate-500">At least 8 characters</span>}
            </label>
            {err && <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</p>}
            <button disabled={busy} className="min-h-11 w-full rounded-lg bg-slate-900 px-4 py-2.5 font-medium text-white hover:bg-slate-800 disabled:opacity-60">
              {busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
            </button>
          </form>
          <button
            className="mt-4 w-full text-sm text-slate-600 hover:underline"
            onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setErr(null) }}
          >
            {mode === 'login' ? "New here? Create an account" : 'Already have an account? Sign in'}
          </button>
        </div>
      </div>
    </div>
  )
}
