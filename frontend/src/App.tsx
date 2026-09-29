import { useQuery } from '@tanstack/react-query'
import { Navigate, NavLink, Outlet, Route, Routes, useNavigate } from 'react-router-dom'
import { api, auth, type Confirmation, type Flagged, type User } from './api'
import AuthCallback from './pages/AuthCallback'
import Bills from './pages/Bills'
import Connect from './pages/Connect'
import Login from './pages/Login'
import Proof from './pages/Proof'
import { JudgeBanner } from './judge'
import Review from './pages/Review'

function RequireAuth() {
  if (!auth.get()) return <Navigate to="/login" replace />
  return <Shell />
}

function Shell() {
  const nav = useNavigate()
  const me = useQuery({ queryKey: ['me'], queryFn: () => api<{ user: User }>('/auth/me') })
  const confs = useQuery({ queryKey: ['confirmations'], queryFn: () => api<Confirmation[]>('/confirmations') })
  const flagged = useQuery({ queryKey: ['flagged'], queryFn: () => api<Flagged[]>('/flagged') })
  const pending = (confs.data?.length ?? 0) + (flagged.data?.length ?? 0)
  const link = ({ isActive }: { isActive: boolean }) =>
    `rounded-lg px-3 py-2 text-sm font-medium min-h-11 inline-flex items-center gap-2 ${isActive ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-200'}`

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-2 px-4 py-2">
          <span className="mr-2 text-lg font-bold tracking-tight">Lifeline</span>
          <nav className="flex flex-wrap gap-1">
            <NavLink to="/connect" className={link}>Connect</NavLink>
            <NavLink to="/inbox" className={link}>
              Review
              {pending > 0 && <span className="rounded-full bg-amber-500 px-1.5 text-xs text-white">{pending}</span>}
            </NavLink>
            <NavLink to="/bills" className={link}>Bills</NavLink>
            <NavLink to="/proof" className={link}>Proven live</NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-2 text-sm text-slate-500">
            <span className="hidden sm:inline">{me.data?.user.email}</span>
            <button
              className="rounded-lg px-3 py-2 hover:bg-slate-200"
              onClick={() => { auth.clear(); nav('/login') }}
            >Sign out</button>
          </div>
        </div>
      </header>
      <JudgeBanner />
      <main className="mx-auto max-w-5xl px-4 py-6">
        <Outlet />
      </main>
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
        <Route path="/connect" element={<Connect />} />
        <Route path="/inbox" element={<Review />} />
        <Route path="/bills" element={<Bills />} />
      </Route>
      <Route path="*" element={<Navigate to={auth.get() ? '/connect' : '/login'} replace />} />
    </Routes>
  )
}
