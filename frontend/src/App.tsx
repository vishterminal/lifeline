import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Link, Navigate, NavLink, Outlet, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { api, auth, type Confirmation, type Flagged, type User } from './api'
import { JudgeBanner } from './judge'
import { Logo } from './ui'
import AuthCallback from './pages/AuthCallback'
import Bills from './pages/Bills'
import CalendarPage from './pages/Calendar'
import Connect from './pages/Connect'
import Login from './pages/Login'
import Overview from './pages/Overview'
import Proof from './pages/Proof'
import Review from './pages/Review'
import Settings from './pages/Settings'

function RequireAuth() {
  if (!auth.get()) return <Navigate to="/login" replace />
  return <Shell />
}

const NAV = [
  { to: '/overview', label: 'Overview' },
  { to: '/connect', label: 'Connect' },
  { to: '/inbox', label: 'Review' },
  { to: '/bills', label: 'Bills' },
  { to: '/calendar', label: 'Calendar' },
  { to: '/settings', label: 'Settings' },
]

function UserMenu({ user }: { user?: User }) {
  const [open, setOpen] = useState(false)
  const nav = useNavigate()
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])
  const name = user?.name || user?.email?.split('@')[0] || 'You'
  const initials = name.split(/[\s._-]+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase()
  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-haspopup="menu"
        className="flex min-h-11 items-center gap-2.5 rounded-full border border-line bg-card py-1 pl-1 pr-3 hover:border-gold/40">
        <span className="grid h-9 w-9 place-items-center rounded-full bg-gradient-to-br from-gold to-gold-2 text-sm font-bold text-bg">{initials}</span>
        <span className="hidden max-w-40 truncate text-sm font-medium text-ink md:inline">{name}</span>
        <svg viewBox="0 0 20 20" className="h-4 w-4 text-muted" fill="currentColor" aria-hidden="true"><path d="M5.3 7.3a1 1 0 0 1 1.4 0L10 10.6l3.3-3.3a1 1 0 1 1 1.4 1.4l-4 4a1 1 0 0 1-1.4 0l-4-4a1 1 0 0 1 0-1.4z" /></svg>
      </button>
      {open && (
        <div role="menu" className="absolute right-0 z-30 mt-2 w-64 overflow-hidden rounded-2xl border border-line bg-card shadow-[var(--shadow-card)]">
          <div className="border-b border-line px-4 py-3">
            <div className="truncate text-sm font-semibold text-ink">{name}</div>
            <div className="truncate text-xs text-muted">{user?.email}</div>
          </div>
          {[['/settings', 'Settings'], ['/connect', 'Connected sources'], ['/proof', 'Proven live']].map(([to, l]) => (
            <Link key={to} to={to} role="menuitem" onClick={() => setOpen(false)} className="block px-4 py-2.5 text-sm text-ink-2 hover:bg-raised hover:text-ink">{l}</Link>
          ))}
          <button role="menuitem" onClick={() => { auth.clear(); nav('/login') }}
            className="block w-full border-t border-line px-4 py-2.5 text-left text-sm text-red-300 hover:bg-red-500/10">Sign out</button>
        </div>
      )}
    </div>
  )
}

function Shell() {
  const loc = useLocation()
  const me = useQuery({ queryKey: ['me'], queryFn: () => api<{ user: User }>('/auth/me') })
  const confs = useQuery({ queryKey: ['confirmations'], queryFn: () => api<Confirmation[]>('/confirmations') })
  const flagged = useQuery({ queryKey: ['flagged'], queryFn: () => api<Flagged[]>('/flagged') })
  const pending = (confs.data?.length ?? 0) + (flagged.data?.length ?? 0)
  const link = ({ isActive }: { isActive: boolean }) =>
    `inline-flex min-h-10 items-center gap-2 whitespace-nowrap rounded-full px-4 text-sm font-medium transition ${isActive ? 'bg-gold text-bg shadow-[0_6px_18px_-8px_rgb(255_209_0/0.8)]' : 'text-ink-2 hover:bg-card hover:text-ink'}`

  useEffect(() => { window.scrollTo(0, 0) }, [loc.pathname])

  return (
    <div className="min-h-screen overflow-x-clip bg-bg">
      <header className="sticky top-0 z-20 border-b border-line bg-bg/85 backdrop-blur-md">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-3 sm:px-6">
          <Logo />
          <nav aria-label="Main" className="mx-auto hidden items-center gap-1 rounded-full border border-line bg-surface/70 p-1 lg:flex">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} className={link}>
                {n.label}
                {n.to === '/inbox' && pending > 0 && <span className="rounded-full bg-bg/80 px-1.5 text-xs font-bold text-gold">{pending}</span>}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2 lg:ml-0">
            <Link to="/inbox" aria-label={`${pending} items need attention`}
              className="relative grid h-11 w-11 place-items-center rounded-full border border-line bg-card text-ink-2 hover:border-gold/40 hover:text-gold">
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
              </svg>
              {pending > 0 && <span className="absolute -right-0.5 -top-0.5 grid h-5 min-w-5 place-items-center rounded-full bg-gold px-1 text-[11px] font-bold text-bg">{pending}</span>}
            </Link>
            <UserMenu user={me.data?.user} />
          </div>
        </div>
        {/* Mobile / tablet nav: pill row in its own horizontal scroller. */}
        <nav aria-label="Main" className="overflow-x-auto border-t border-line px-4 py-2 lg:hidden">
          <div className="flex w-max gap-1">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} className={link}>
                {n.label}
                {n.to === '/inbox' && pending > 0 && <span className="rounded-full bg-bg/80 px-1.5 text-xs font-bold text-gold">{pending}</span>}
              </NavLink>
            ))}
          </div>
        </nav>
      </header>
      <JudgeBanner />
      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
        <Outlet />
      </main>
      <footer className="mx-auto max-w-7xl px-4 pb-10 text-xs text-muted sm:px-6">
        Lifeline stores only extracted bill details — never your emails or messages. · <Link to="/proof" className="hover:text-gold">Proven live</Link>
      </footer>
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/auth/callback" element={<AuthCallback />} />
      <Route path="/proof" element={<Proof />} />
      <Route element={<RequireAuth />}>
        <Route path="/overview" element={<Overview />} />
        <Route path="/connect" element={<Connect />} />
        <Route path="/inbox" element={<Review />} />
        <Route path="/bills" element={<Bills />} />
        <Route path="/calendar" element={<CalendarPage />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<Navigate to={auth.get() ? '/overview' : '/login'} replace />} />
    </Routes>
  )
}
