import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, ApiError, day, type DocumentRow } from '../api'
import { Badge, Button, Card, EmptyState, inputCls, Notice, PageHeader } from '../ui'

const KINDS: [string, string, string][] = [
  ['PUC', 'PUC certificate', '🚘'], ['INSURANCE_VEHICLE', 'Vehicle insurance', '🏍️'], ['DRIVING_LICENCE', 'Driving licence', '🪪'],
  ['VEHICLE_RC', 'Vehicle RC', '📄'], ['PASSPORT', 'Passport', '🛂'], ['INSURANCE_OTHER', 'Health / life insurance', '🛡️'], ['OTHER', 'Other document', '📁'],
]
const ICON = Object.fromEntries(KINDS.map(([k, , i]) => [k, i]))

export default function Documents() {
  const qc = useQueryClient()
  const docs = useQuery({ queryKey: ['documents'], queryFn: () => api<DocumentRow[]>('/documents') })
  const empty = { kind: 'PUC', label: 'PUC certificate', number: '', vehicle_ref: '', expiry_date: '' }
  const [f, setF] = useState(empty)
  const [msg, setMsg] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null)
  const refresh = () => ['documents', 'bills', 'obligations', 'lifeload'].forEach((k) => qc.invalidateQueries({ queryKey: [k] }))
  const add = useMutation({
    mutationFn: () => api('/documents', { method: 'POST', json: { ...f, number: f.number || undefined, vehicle_ref: f.vehicle_ref || undefined } }),
    onSuccess: () => { setF(empty); setMsg({ tone: 'ok', text: 'Saved — Lifeline will remind you before it expires.' }); refresh() },
    onError: (e) => setMsg({ tone: 'error', text: e instanceof ApiError ? e.message : 'Could not save' }),
  })
  const del = useMutation({ mutationFn: (id: string) => api(`/documents/${id}`, { method: 'DELETE' }), onSuccess: refresh })
  const label = 'block text-sm font-medium text-ink-2'
  const vehicle = ['PUC', 'INSURANCE_VEHICLE', 'VEHICLE_RC'].includes(f.kind)

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader title="Documents" subtitle="Expiry dates of your certificates and IDs — only the date and the last 4 characters are kept, never the file." />
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-5 [&>*]:min-w-0">
        <Card title="Add a document" className="lg:col-span-2">
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); setMsg(null); add.mutate() }}>
            <label className={label}>Type
              <select className={`${inputCls} mt-1 w-full`} value={f.kind}
                onChange={(e) => { const k = KINDS.find((x) => x[0] === e.target.value)!; setF({ ...f, kind: k[0], label: k[1] }) }}>
                {KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
            </label>
            <label className={label}>Name
              <input className={`${inputCls} mt-1 w-full`} required value={f.label} onChange={(e) => setF({ ...f, label: e.target.value })} />
            </label>
            <label className={label}>Number (optional — only the last 4 are kept)
              <input className={`${inputCls} mt-1 w-full`} value={f.number} onChange={(e) => setF({ ...f, number: e.target.value })} />
            </label>
            {vehicle && (
              <label className={label}>Vehicle number
                <input className={`${inputCls} mt-1 w-full`} placeholder="TN 09 AB 1234" value={f.vehicle_ref} onChange={(e) => setF({ ...f, vehicle_ref: e.target.value })} />
              </label>
            )}
            <label className={label}>Expiry date
              <input className={`${inputCls} mt-1 w-full`} type="date" required value={f.expiry_date} onChange={(e) => setF({ ...f, expiry_date: e.target.value })} />
            </label>
            {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
            <Button type="submit" className="w-full" disabled={add.isPending}>{add.isPending ? 'Saving…' : 'Save document'}</Button>
          </form>
        </Card>
        <div className="space-y-3 lg:col-span-3">
          {docs.data?.length === 0 && <EmptyState>No documents yet. Add your PUC, insurance or licence and Lifeline tracks the renewal — including the PUC → insurance chain.</EmptyState>}
          {docs.data?.map((d) => (
            <Card key={d.id}>
              <div className="flex items-start gap-3">
                <div className="glass-inner grid h-11 w-11 shrink-0 place-items-center rounded-xl text-xl" aria-hidden="true">{ICON[d.kind] ?? '📄'}</div>
                <div className="min-w-0 flex-1">
                  <div className="font-semibold">{d.label}</div>
                  <div className="text-sm text-muted">
                    Expires {day(d.expiry_date)}{d.number_last4 ? ` · ••••${d.number_last4}` : ''}{d.vehicle_ref ? ` · ${d.vehicle_ref}` : ''}
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {d.days_left < 0 ? <Badge tone="red">Expired {-d.days_left} day(s) ago</Badge>
                      : d.days_left <= 30 ? <Badge tone="amber">Expires in {d.days_left} days</Badge> : <Badge tone="green">Valid · {d.days_left} days left</Badge>}
                    <Badge>🔔 Renewal reminders on</Badge>
                  </div>
                </div>
                <Button variant="ghost" onClick={() => del.mutate(d.id)} aria-label={`Remove ${d.label}`}>Remove</Button>
              </div>
            </Card>
          ))}
        </div>
      </div>
    </div>
  )
}
