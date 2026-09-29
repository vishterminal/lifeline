// Web push: register the service worker, ask permission, subscribe, send the subscription.
import { api } from './api'

export function pushSupported() {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
}

export async function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return null
  try { return await navigator.serviceWorker.register('/sw.js') } catch { return null }
}

function urlB64ToUint8Array(b64: string) {
  const pad = '='.repeat((4 - (b64.length % 4)) % 4)
  const raw = atob((b64 + pad).replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)))
}

export async function enablePush(): Promise<string> {
  if (!pushSupported()) throw new Error('This browser does not support notifications. On iPhone, add Lifeline to the Home Screen first.')
  const { enabled, key } = await api<{ enabled: boolean; key: string | null }>('/push/vapid-public-key')
  if (!enabled || !key) throw new Error("Push isn't configured on this server.")
  const perm = await Notification.requestPermission()
  if (perm !== 'granted') throw new Error('Notifications were blocked. Allow them in your browser settings and try again.')
  const reg = (await registerServiceWorker()) ?? (await navigator.serviceWorker.ready)
  const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlB64ToUint8Array(key) })
  const json = sub.toJSON()
  await api('/push/subscribe', { method: 'POST', json: { endpoint: json.endpoint, keys: json.keys } })
  return 'Notifications are on for this browser.'
}
