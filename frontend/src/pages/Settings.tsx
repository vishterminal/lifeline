import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError, auth, day, type Source, type User } from '../api'
import { Button, Card, inputCls, Notice, PageHeader, StatusBadge } from '../ui'

// Uses the existing GET/PUT /api/profile endpoints only.
export default function Settings() {
  const qc = useQueryClient()
  const nav = useNavigate()
  const profile = useQuery({ queryKey: ['profile'], queryFn: () => api<User>('/profile') })
  const sources = useQuery({ queryKey: ['sources'], queryFn: () => api<Source[]>('/sources') })
  const [form, setForm] = useState({ name: '', phone_e164: '', salary_day: '', balance_amount: '', allow_cloud_image_processing: false })
  const [msg, setMsg] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null)

  useEffect(() => {
    const p = profile.data
    if (p) setForm({
      name: p.name ?? '', phone_e164: p.phone_e164 ?? '', salary_day: p.salary_day?.toString() ?? '',
      balance_amount: p.balance_amount ?? '', allow_cloud_image_processing: p.allow_cloud_image_processing,
    })
  }, [profile.data])

  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = { name: form.name || null, allow_cloud_image_processing: form.allow_cloud_image_processing }
      if (form.phone_e164.trim()) body.phone_e164 = form.phone_e164.replace(/\s/g, '')
      if (form.salary_day) body.salary_day = Number(form.salary_day)
      if (form.balance_amount !== '' && form.balance_amount !== (profile.data?.balance_amount ?? '')) body.balance_amount = form.balance_amount
      return api<User>('/profile', { method: 'PUT', json: body })
    },
    onSuccess: () => { setMsg({ tone: 'ok', text: 'Saved.' }); ['profile', 'me'].forEach((k) => qc.invalidateQueries({ queryKey: [k] })) },
    onError: (e) => setMsg({ tone: 'error', text: e instanceof ApiError ? e.message : 'Could not save' }),
  })

  const label = 'block text-sm font-medium text-ink-2'
  return (
    <div>
      <PageHeader title="Settings" subtitle="Your profile, money snapshot and privacy choices." />
      <div className="grid grid-cols-1 [&>*]:min-w-0 gap-5 lg:grid-cols-3">
        <Card title="Profile & money" subtitle="Used for the Overview balance and planning." className="lg:col-span-2">
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
            <label className={`${label} sm:col-span-2`}>Current balance (₹)
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
          <Button variant="danger" className="w-full" onClick={() => { auth.clear(); nav('/login') }}>Sign out</Button>
        </div>
      </div>
    </div>
  )
}
