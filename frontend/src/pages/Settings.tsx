import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError, auth, day, type FamilyContact, type Source, type User } from '../api'
import { enablePush } from '../push'
import { Button, Card, inputCls, Notice, PageHeader, StatusBadge } from '../ui'

// Uses the existing GET/PUT /api/profile endpoints only.
export default function Settings() {
  const qc = useQueryClient()
  const nav = useNavigate()
  const profile = useQuery({ queryKey: ['profile'], queryFn: () => api<User>('/profile') })
  const sources = useQuery({ queryKey: ['sources'], queryFn: () => api<Source[]>('/sources') })
  const [form, setForm] = useState({ name: '', phone_e164: '', salary_day: '', balance_amount: '', salary_amount: '', allow_cloud_image_processing: false })
  const [msg, setMsg] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null)

  useEffect(() => {
    const p = profile.data
    if (p) setForm({
      name: p.name ?? '', phone_e164: p.phone_e164 ?? '', salary_day: p.salary_day?.toString() ?? '',
      balance_amount: p.balance_amount ?? '', salary_amount: p.salary_amount ?? '', allow_cloud_image_processing: p.allow_cloud_image_processing,
    })
  }, [profile.data])

  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = { name: form.name || null, allow_cloud_image_processing: form.allow_cloud_image_processing }
      if (form.phone_e164.trim()) body.phone_e164 = form.phone_e164.replace(/\s/g, '')
      if (form.salary_day) body.salary_day = Number(form.salary_day)
      if (form.balance_amount !== '' && form.balance_amount !== (profile.data?.balance_amount ?? '')) body.balance_amount = form.balance_amount
      if (form.salary_amount !== '') body.salary_amount = form.salary_amount
      return api<User>('/profile', { method: 'PUT', json: body })
    },
    onSuccess: () => { setMsg({ tone: 'ok', text: 'Saved.' }); ['profile', 'me'].forEach((k) => qc.invalidateQueries({ queryKey: [k] })) },
    onError: (e) => setMsg({ tone: 'error', text: e instanceof ApiError ? e.message : 'Could not save' }),
  })

  const label = 'block text-sm font-medium text-ink-2'
  return (
    <div>
      <PageHeader title="Settings" subtitle="Your profile, money snapshot and privacy choices." />
      <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-3 [&>*]:min-w-0">
        <div className="space-y-5 lg:col-span-2">
        <Card title="Profile & money" subtitle="Used for the Overview balance and planning.">
          <form className="grid grid-cols-1 [&>*]:min-w-0 gap-4 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); setMsg(null); save.mutate() }}>
            <label className={label}>Name
              <input className={`${inputCls} mt-1 w-full`} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} autoComplete="name" />
            </label>
            <label className={label}>Email
              <input className={`${inputCls} mt-1 w-full opacity-70`} value={profile.data?.email ?? ''} readOnly />
            </label>
            <label className={label}>WhatsApp number
              <input className={`${inputCls} mt-1 w-full`} value={form.phone_e164} placeholder="+919876543210" onChange={(e) => setForm({ ...form, phone_e164: e.target.value })} />
              <span className="mt-1 block text-xs text-muted">With country code (E.164).</span>
            </label>
            <label className={label}>Salary day
              <input className={`${inputCls} mt-1 w-full`} type="number" min={1} max={31} value={form.salary_day} onChange={(e) => setForm({ ...form, salary_day: e.target.value })} />
              <span className="mt-1 block text-xs text-muted">Day of the month your salary arrives (1–31).</span>
            </label>
            <label className={label}>Monthly salary (₹, optional)
              <input className={`${inputCls} mt-1 w-full`} inputMode="decimal" value={form.salary_amount} onChange={(e) => setForm({ ...form, salary_amount: e.target.value })} />
              <span className="mt-1 block text-xs text-muted">Used by the cash-flow planner.</span>
            </label>
            <label className={label}>Current balance (₹)
              <input className={`${inputCls} mt-1 w-full`} inputMode="decimal" value={form.balance_amount} onChange={(e) => setForm({ ...form, balance_amount: e.target.value })} />
              <span className="mt-1 block text-xs text-muted">
                A snapshot, not live bank data{profile.data?.balance_as_of ? ` · last set ${day(profile.data.balance_as_of)}` : ''}.
              </span>
            </label>
            <label className="flex items-start gap-3 rounded-2xl border border-line bg-surface/60 p-4 sm:col-span-2">
              <input type="checkbox" className="mt-1 h-5 w-5 accent-[#FFD100]" checked={form.allow_cloud_image_processing}
                onChange={(e) => setForm({ ...form, allow_cloud_image_processing: e.target.checked })} />
              <span>
                <span className="block text-sm font-medium text-ink">Allow cloud reading of bill photos</span>
                <span className="block text-xs text-muted">Only used when a photo can't be read on this computer. Off by default; text is always redacted before any AI call.</span>
              </span>
            </label>
            <div className="flex flex-wrap items-center gap-3 sm:col-span-2">
              <Button type="submit" disabled={save.isPending}>{save.isPending ? 'Saving…' : 'Save changes'}</Button>
              {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
            </div>
          </form>
        </Card>
        <div className="grid grid-cols-1 items-start gap-5 md:grid-cols-2 [&>*]:min-w-0">
          <NotificationsCard />
          <FamilyCard />
        </div>
        </div>

        <div className="space-y-5">
          <Card title="Connected sources">
            <ul className="space-y-3">
              {(sources.data ?? []).map((s) => (
                <li key={s.kind} className="flex items-center justify-between text-sm">
                  <span className="text-ink-2">{s.kind === 'GMAIL' ? 'Gmail (read-only)' : s.kind === 'SMS' ? 'SMS forwarder' : 'WhatsApp'}</span>
                  <StatusBadge status={s.status} />
                </li>
              ))}
            </ul>
            <Link to="/connect" className="mt-4 inline-block text-sm font-medium text-gold hover:underline">Manage sources →</Link>
          </Card>
          <Card title="Privacy">
            <ul className="space-y-2 text-sm text-ink-2">
              <li>• Only bill details are stored — never full emails or messages.</li>
              <li>• OTPs are dropped instantly and never saved.</li>
              <li>• Card, account, Aadhaar, PAN and phone numbers are masked before any AI call.</li>
              <li>• Gmail access is read-only and can be disconnected any time.</li>
            </ul>
          </Card>
          <Button variant="secondary" className="w-full" onClick={() => { auth.clear(); nav('/login') }}>Sign out</Button>
          <DeleteAll />
        </div>
      </div>
    </div>
  )
}


function FamilyCard() {
  const qc = useQueryClient()
  const fam = useQuery({ queryKey: ['family'], queryFn: () => api<FamilyContact[]>('/family') })
  const [f, setF] = useState({ name: '', phone_e164: '+91', consented: false })
  const [err, setErr] = useState<string | null>(null)
  const add = useMutation({
    mutationFn: () => api('/family', { method: 'POST', json: { ...f, phone_e164: f.phone_e164.replace(/\s/g, '') } }),
    onSuccess: () => { setF({ name: '', phone_e164: '+91', consented: false }); setErr(null); qc.invalidateQueries({ queryKey: ['family'] }) },
    onError: (e) => setErr(e instanceof ApiError ? e.message : 'Failed'),
  })
  const del = useMutation({ mutationFn: (id: string) => api(`/family/${id}`, { method: 'DELETE' }), onSuccess: () => qc.invalidateQueries({ queryKey: ['family'] }) })
  return (
    <Card title="Family alert" subtitle="Last resort for high-risk bills: if you haven't responded to 3 reminders and it's due within 24 h, they get one WhatsApp.">
      <ul className="mb-3 space-y-2">
        {(fam.data ?? []).map((c) => (
          <li key={c.id} className="flex items-center justify-between gap-2 text-sm">
            <span>{c.name} <span className="text-muted">{c.phone_e164}</span></span>
            <Button variant="ghost" onClick={() => del.mutate(c.id)} aria-label={`Remove ${c.name}`}>Remove</Button>
          </li>
        ))}
        {fam.data?.length === 0 && <li className="text-sm text-muted">No one added.</li>}
      </ul>
      <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); add.mutate() }}>
        <input className={`${inputCls} w-full`} placeholder="Name" aria-label="Family member name" required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        <input className={`${inputCls} w-full`} placeholder="+919876543210" aria-label="Family member phone" required value={f.phone_e164} onChange={(e) => setF({ ...f, phone_e164: e.target.value })} />
        <label className="flex items-start gap-2 text-xs text-ink-2">
          <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[#FFD100]" checked={f.consented} onChange={(e) => setF({ ...f, consented: e.target.checked })} />
          They agreed to receive these alerts.
        </label>
        {err && <Notice tone="error">{err}</Notice>}
        <Button type="submit" variant="secondary" className="w-full" disabled={add.isPending}>Add family contact</Button>
      </form>
    </Card>
  )
}

function DeleteAll() {
  const nav = useNavigate()
  const [text, setText] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const del = useMutation({
    mutationFn: () => api('/me/data', { method: 'DELETE', json: { confirm: text } }),
    onSuccess: () => { auth.clear(); nav('/login') },
    onError: (e) => setErr(e instanceof ApiError ? e.message : 'Failed'),
  })
  return (
    <section className="glass rounded-[var(--radius-card)] !border-red-400/30 p-5">
      <h2 className="font-semibold text-red-300">Delete all my data</h2>
      <p className="mt-1 text-sm text-muted">Removes your account, bills, reminders, connected-source tokens and everything else. This can't be undone.</p>
      <label className="mt-3 block text-xs text-ink-2">Type <b>DELETE</b> to confirm
        <input className={`${inputCls} mt-1 w-full`} value={text} onChange={(e) => setText(e.target.value)} aria-label="Type DELETE to confirm" />
      </label>
      {err && <div className="mt-2"><Notice tone="error">{err}</Notice></div>}
      <Button variant="danger" className="mt-3 w-full" disabled={text.trim().toUpperCase() !== 'DELETE' || del.isPending} onClick={() => del.mutate()}>
        {del.isPending ? 'Deleting…' : 'Delete everything'}
      </Button>
    </section>
  )
}


function NotificationsCard() {
  const [msg, setMsg] = useState<{ tone: 'ok' | 'error' | 'info'; text: string } | null>(null)
  const status = useQuery({ queryKey: ['push-status'], queryFn: () => api<{ enabled: boolean; subscriptions: number }>('/push/status') })
  const qc = useQueryClient()
  const on = useMutation({
    mutationFn: enablePush,
    onSuccess: (t) => { setMsg({ tone: 'ok', text: t }); qc.invalidateQueries({ queryKey: ['push-status'] }) },
    onError: (e) => setMsg({ tone: 'error', text: (e as Error).message }),
  })
  const test = useMutation({
    mutationFn: () => api<{ delivered: number }>('/push/test', { method: 'POST' }),
    onSuccess: (r) => setMsg({ tone: 'ok', text: `Test notification sent to ${r.delivered} browser(s).` }),
    onError: (e) => setMsg({ tone: 'error', text: e instanceof ApiError ? e.message : 'Failed' }),
  })
  return (
    <Card title="Notifications" subtitle="Get reminder pop-ups on this device, even when Lifeline isn't open.">
      <p className="mb-3 text-sm text-muted">{status.data?.subscriptions ? `On for ${status.data.subscriptions} browser(s).` : 'Off on this device.'} On iPhone, add Lifeline to your Home Screen first.</p>
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => on.mutate()} disabled={on.isPending}>{on.isPending ? 'Enabling…' : 'Enable notifications'}</Button>
        <Button variant="secondary" onClick={() => test.mutate()} disabled={test.isPending}>Send test</Button>
      </div>
      {msg && <div className="mt-3"><Notice tone={msg.tone}>{msg.text}</Notice></div>}
    </Card>
  )
}
