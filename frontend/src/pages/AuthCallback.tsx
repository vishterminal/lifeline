import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { auth } from '../api'

// Google sign-in lands here with #token=...&next=/connect
export default function AuthCallback() {
  const nav = useNavigate()
  const handled = useRef(false) // StrictMode runs effects twice in dev
  useEffect(() => {
    if (handled.current) return
    handled.current = true
    const p = new URLSearchParams(window.location.hash.slice(1))
    const token = p.get('token')
    if (token) {
      auth.set(token)
      history.replaceState(null, '', '/auth/callback') // drop the token from the URL
      nav(p.get('next') === '/inbox' ? '/inbox' : '/connect', { replace: true })
    } else {
      nav('/login?error=state_mismatch', { replace: true })
    }
  }, [nav])
  return <p className="p-8 text-ink-2">Signing you in…</p>
}
