// Lifeline service worker: shows reminder push notifications and opens the app on click.
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()))
self.addEventListener('push', (event) => {
  let data = { title: 'Lifeline', body: 'You have a reminder.', url: '/reminders' }
  try { data = { ...data, ...event.data.json() } } catch (_) { /* plain text */ }
  event.waitUntil(self.registration.showNotification(data.title, {
    body: data.body, icon: '/icon-192.png', badge: '/icon-192.png', data: { url: data.url }, tag: 'lifeline-reminder', renotify: true,
  }))
})
self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const url = (event.notification.data && event.notification.data.url) || '/reminders'
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((wins) => {
    for (const w of wins) { if ('focus' in w) { w.navigate(url); return w.focus() } }
    return self.clients.openWindow(url)
  }))
})
