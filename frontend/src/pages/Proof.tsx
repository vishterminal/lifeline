import { useState } from 'react'
import { Link } from 'react-router-dom'
import { auth } from '../api'

// Screenshots from the team's real run (live keys, real Gmail / phone).
// Files live in frontend/public/proof/. Missing ones are simply not shown.
const SHOTS: { file: string; title: string; caption: string }[] = [
  { file: 'google-signin.png', title: 'Real Google sign-in', caption: '"Continue with Google" opens Google\'s own account picker for the Lifeline app (OpenID Connect: openid, email, profile).' },
  { file: 'signed-in.png', title: 'Signed in with a real Google account', caption: 'The account is created from the verified Google email — no password stored.' },
  { file: 'gmail-consent.png', title: 'Read-only Gmail consent', caption: 'Lifeline asks only for gmail.readonly. It refuses any broader permission.' },
  { file: 'gmail-connected.png', title: 'Real inbox connected and checked', caption: 'Gmail API search for bill-like mail only; non-matching mail is never downloaded.' },
  { file: 'gmail-bill.png', title: 'A real bill found in a real inbox', caption: 'A Google Play subscription email was extracted, sender-checked and put in Review — no manual forwarding.' },
  { file: 'whatsapp-reply.png', title: 'Real WhatsApp reply', caption: 'A bill forwarded from a phone to the Twilio sandbox number, answered by Lifeline.' },
]

const VERIFIED = [
  ['Google sign-in (OAuth 2.0 / OpenID Connect)', 'Real Google account, testing-mode OAuth client, state cookie checked.'],
  ['Gmail read-only connect', 'Google granted exactly https://www.googleapis.com/auth/gmail.readonly — verified via Google\'s tokeninfo.'],
  ['Gmail API inbox read', 'Real inbox searched; a Google Play bill was found, extracted and sent to Review.'],
  ['Clear error when Gmail API is disabled', 'Found live (SERVICE_DISABLED) and turned into an actionable message in the UI.'],
  ['Public webhook for WhatsApp / SMS', 'Backend reachable over HTTPS through an ngrok tunnel for Twilio and the Android forwarder.'],
]

function Shot({ s }: { s: (typeof SHOTS)[number] }) {
  const [ok, setOk] = useState(true)
  if (!ok) return null
  return (
    <figure className="overflow-hidden rounded-2xl border border-line bg-card shadow-sm">
      <img src={`/proof/${s.file}`} alt={s.title} onError={() => setOk(false)} className="w-full bg-raised object-contain" loading="lazy" />
      <figcaption className="p-4">
        <div className="font-semibold">{s.title}</div>
        <div className="text-sm text-ink-2">{s.caption}</div>
      </figcaption>
    </figure>
  )
}

export default function Proof() {
  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-8">
      <div>
        <Link to={auth.get() ? '/connect' : '/login'} className="text-sm text-ink-2 hover:underline">← Back to the app</Link>
        <h1 className="mt-2 text-3xl font-bold tracking-tight text-ink sm:text-4xl">Proven <span className="text-gold">live</span></h1>
        <p className="mt-1 max-w-3xl text-ink-2">
          The version you're running from GitHub is in <b>judge mode</b>: without our Google and Twilio keys, Gmail,
          WhatsApp and SMS run on sample messages through the <b>same pipeline</b>. With keys in <code>.env</code>, the
          same buttons talk to the real services. This is what that looked like on our machine.
        </p>
      </div>

      <section className="rounded-2xl border border-emerald-400/30 bg-emerald-500/10 p-5">
        <h2 className="text-lg font-semibold text-emerald-300">Verified against real services</h2>
        <ul className="mt-3 space-y-2">
          {VERIFIED.map(([t, d]) => (
            <li key={t} className="flex gap-2 text-sm">
              <span aria-hidden="true">✅</span>
              <span><b>{t}</b> — {d}</span>
            </li>
          ))}
        </ul>
      </section>

      <div className="grid grid-cols-1 [&>*]:min-w-0 gap-5 md:grid-cols-2">
        {SHOTS.map((s) => <Shot key={s.file} s={s} />)}
      </div>

      <section className="rounded-2xl border border-line bg-card p-5 text-sm text-ink-2">
        <h2 className="text-lg font-semibold text-ink">Run it live yourself</h2>
        <ol className="mt-2 list-decimal space-y-1 pl-5">
          <li>Create a Google OAuth client (Web) with redirect URIs <code>http://localhost:8000/api/auth/google/callback</code> and <code>http://localhost:8000/api/sources/gmail/callback</code>; enable the Gmail API.</li>
          <li>Put <code>GOOGLE_CLIENT_ID</code>, <code>GOOGLE_CLIENT_SECRET</code>, <code>TOKEN_ENCRYPTION_KEY</code> and <code>CONNECTOR_MODE=live</code> in <code>.env</code>.</li>
          <li>For WhatsApp / SMS: run <code>ngrok http 8000</code>, set <code>PUBLIC_BASE_URL</code>, add Twilio keys, and point the sandbox webhook at <code>/api/webhooks/twilio/whatsapp</code>.</li>
        </ol>
        <p className="mt-2">Full steps: <code>docs/SETUP_HUMAN_STEPS.md</code> in the repository.</p>
      </section>
    </div>
  )
}
