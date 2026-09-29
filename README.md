# Lifeline

**Track everything, miss nothing.** Lifeline collects your bills, renewals and dues from **Gmail, WhatsApp and SMS** automatically, checks the sender is genuine, blocks fake and phishing bills, and shows everything that needs you in one place.

> Uproot Innovation Hackathon, Problem 3: *Fragmented Life Administration & Obligation Fatigue*

![Overview](docs/screenshots/overview.png)

---

## ▶ Run it (judges: one command)

**Needs:** Python 3.10 or newer. Node, accounts and API keys are **not** needed.

| OS | Command |
|---|---|
| **Windows** | Double-click **`start.bat`** (or run it in a terminal) |
| **macOS / Linux** | `./start.sh` |

The first run creates a private Python environment and installs dependencies (1–3 minutes). Then it opens **http://localhost:8000**.

**Then:**
1. On the landing page, fill in **Create new account** (any name, email and password). Email accounts open straight into **judge demo mode**. *Continue with Google* is the real, live path.
2. On **Connect**, open **🎓 Judge demo → ▶ Run full demo**. It connects a sample Gmail inbox, forwards a bill on WhatsApp, and sends SMS: a bill, an OTP, and a message the two readers disagree on. Or use the phones yourself.
3. Open **Review** and confirm the TNEB bill. It arrived through **three channels** but is shown **once**. Amounts are pre-filled from what was detected.
4. Back on **Connect**, the reviewed SMS has left the phone. Forward the **payment debited** SMS and the bill is **marked paid by itself**.
5. **Review → Suspicious** shows the fake "Netflix" email blocked, with the reasons.
6. **Bills** is ranked by **₹ risk**, not date. The **PUC certificate (no amount!) is #1**, because missing it blocks the bike-insurance renewal. Click it for the chain, **🔮 What if I skip this?**, and **Pay now (simulated)**.
7. **Overview** is the money dashboard. **🎓 Judge demo → Reset** replays everything.

### Judge mode vs live mode

The GitHub copy runs in **judge mode**. There are no Google or Twilio keys, so every source runs on realistic sample messages, **through the same pipeline code** the live integrations use. With keys in `.env`, the same screens connect to a real Gmail inbox, a WhatsApp number and an Android SMS forwarder.

**We ran it live.** The in-app **"Proven live"** page lists what was verified against real services:
- real Google sign-in
- Gmail read-only consent (`gmail.readonly` only, checked with Google's tokeninfo)
- a real bill pulled from a real inbox
- the public HTTPS webhook

Screenshots go in `frontend/public/proof/`.

---

## What it does

| | Feature | How |
|---|---|---|
| ✉️ | **Gmail, fully automatic** | Google OAuth (read-only). Only bill-like mail is searched and downloaded, then polled every 15 min. |
| 💬 | **WhatsApp** | Forward any bill (text, photo or PDF) to the Twilio sandbox number. Signature-checked webhook, instant reply. `WHAT'S DUE` and `HELP` commands. |
| 📱 | **SMS (Android)** | A free SMS-forwarder app POSTs bill SMS to a token-protected webhook. OTPs are dropped on the phone *and* on the server. |
| 📎 | **Fallbacks** | Photo/PDF upload, manual entry, and bank-statement CSV (finds recurring charges like Netflix). |
| 🛡️ | **Fake-bill detection** | Sender domain vs the official list, look-alike domains (`netf1ix`), SPF/DKIM/DMARC, link-text ≠ link-target, pressure wording, "company never asks for payment" rules, personal-mailbox senders, and a **cross-check with your own payment history**. |
| 🧠 | **Two independent readers** | An AI extractor and a rules extractor read every message. If they disagree on an amount or date, **you** choose; Lifeline never guesses. |
| 🔁 | **Dedup, paid detection, recurring** | The same bill arriving through several channels becomes one item. A "debited" SMS or receipt closes the matching bill. Monthly and annual renewals are detected. |
| 🔒 | **Privacy by design** | Raw messages are **never stored or logged**. Only the extracted biller, amount and date are kept. Card, account, Aadhaar, PAN and phone numbers are masked **before** any AI call. A test scans the database file to prove this. |
| ₹ | **Ranked by real consequence** | Each bill's cost if missed = late fee or lapse cost + knock-on effects through the **obligation graph** (table-driven rules, e.g. *PUC → blocks → vehicle insurance*). HIGH/MEDIUM/LOW tiers, and every number labelled **Verified** or **Estimated**. |
| 🔮 | **What-if + one-tap pay** | "What if I skip this?" shows the dated chain of effects. Pay is **simulated** (no real money moves) and never uses links from the message. Mark paid, dismiss, snooze. |
| 📊 | **Dashboard** | Overview (balance snapshot, penalties at stake, highest-risk bill, weekly payments chart, alerts), Review, Bills, Calendar, Settings. |

![Connect](docs/screenshots/connect.png)

## How a message flows

```mermaid
flowchart LR
  G[Gmail poll] --> P
  W[WhatsApp webhook] --> P
  S[SMS webhook] --> P
  U[Upload / manual / statement] --> P
  P[Hash + dedup] --> F{OTP or not a bill?}
  F -- yes --> X[Dropped - nothing stored]
  F -- no --> R[Redact sensitive numbers]
  R --> A[AI reader] & B[Rules reader]
  A & B --> C{Agree?}
  C -- no --> Q[Review: you choose]
  C -- yes --> T{Sender trust check}
  T -- suspicious --> FL[Flagged, not added]
  T -- new biller / unsure --> Q
  T -- trusted --> K{Receipt or bill?}
  K -- receipt --> PD[Mark matching bill paid + detect recurring]
  K -- bill --> SV[Save or merge into existing bill]
```

Code: `backend/app/services/pipeline.py`. Every input takes this one path.

## Tech stack

- **Backend:** Python, FastAPI, SQLAlchemy (SQLite), APScheduler, httpx (Google OAuth + Gmail REST), Twilio SDK (webhook signatures), pdfplumber, dateparser, bcrypt + JWT, Fernet for encrypted OAuth tokens
- **AI:** An LLM with structured JSON output (optional; `requirements-live.txt`). Judge mode uses a deterministic mock extractor.
- **Frontend:** React, TypeScript, Vite, Tailwind CSS, TanStack Query. The built app is committed and served by the backend, so there is one URL.

## Tests

Backend: **83 tests**. End to end: `e2e/click_through.py` clicks every button in a real browser (19 steps, 0 console errors).


```bash
cd backend && .venv/Scripts/python -m pytest      # Windows
cd backend && .venv/bin/python -m pytest          # macOS / Linux
```

The backend tests cover:
- OTP filter and redaction
- both extractors and reconcile
- trust scoring, including "a friend sends a fake bill from Gmail"
- dedup and cross-channel merge
- paid detection and recurring detection
- SMS and Twilio webhooks (bad token, bad signature)
- Gmail OAuth state and expiry
- upload limits
- ₹-risk ranking, the PUC → insurance chain, what-if, mock pay, and rejection of "Verified" without a source
- the full judge demo
- a scan of the database file proving no message text is stored

## Going live (optional)

See **[docs/SETUP_HUMAN_STEPS.md](docs/SETUP_HUMAN_STEPS.md)** for the Google OAuth client, Gmail API, Twilio WhatsApp sandbox, ngrok, and the Android SMS forwarder. Copy `.env.example` to `.env`, fill in the keys, and run `start.bat` again.

## Troubleshooting

| Problem | Fix |
|---|---|
| `Python 3.10 or newer is required` | Install Python and tick **Add python.exe to PATH**. |
| Port 8000 already in use | Close the other app, or run `cd backend && .venv\Scripts\python -m uvicorn app.main:app --port 8001` and open that port. |
| Windows says an *Application Control policy has blocked* a file | `start.bat` handles this automatically by reinstalling SQLAlchemy as pure Python. |
| `pip` path-length error on Windows | Clone into a short folder such as `C:\lifeline`. |

## Repository layout

```
start.bat / start.sh      one-command launchers
backend/app/              FastAPI app: routers/, services/ (pipeline, trust, extraction, gmail, whatsapp, sms), llm/, data/
backend/tests/            83 tests
e2e/click_through.py      browser click-through of every button
frontend/src/             React app: pages/ (Overview, Connect, Review, Bills, Calendar, Settings, Proof), judge mode, simulators
frontend/dist/            built web app, served at http://localhost:8000
docs/                     setup steps and screenshots
the product specification full product specification
```

## Status

- **Built:**
  - the input side end to end (collect, understand, verify, dedupe, detect payments and subscriptions)
  - ₹-consequence ranking with the obligation graph
  - what-if
  - simulated one-tap pay
  - the dashboard UI
- **Penalty figures:** the seeded numbers are **illustrative placeholders, always labelled Estimated**. Sourced figures go in `backend/app/data/penalty_rules_seed.json`. The loader refuses "Verified" without a real source.
- **Next:**
  - escalating reminders (push / WhatsApp / family alert)
  - cash-flow planner
  - the penalty-waiver letter drafter
  - These are all specified in the product specification.
