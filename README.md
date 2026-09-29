# Lifeline — input side

This is the ingestion half of Lifeline (see the product specification). It collects bills automatically, works out what each one is, and either puts it on the timeline, asks you to confirm it, or flags it as suspicious.

**Built:** Gmail (read-only), SMS forwarder webhook, WhatsApp sandbox inbound, photo/PDF upload, manual entry, bank-statement import, the shared pipeline, and the review endpoints.
**Not built yet (output side):** ₹-consequence ranking, obligation graph, reminders and escalation, push, outbound WhatsApp, mock pay, Penalty Fighter, cash-flow, and the frontend.

## Run it (mock mode, no accounts needed)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# Windows with Smart App Control / App Control: SQLAlchemy's compiled extension is blocked.
# Reinstall it as pure Python:
#   set DISABLE_SQLALCHEMY_CEXT=1 && pip install --force-reinstall --no-deps --no-binary sqlalchemy sqlalchemy
copy ..\.env.example ..\.env    # optional: defaults are all mock
uvicorn app.main:app --reload --port 8000
```

Frontend (second terminal):

```bash
cd frontend
npm install
npm run dev        # open http://localhost:5173
```

Screens: **Login** (Continue with Google / email) → **Connect** (Gmail, WhatsApp sandbox, SMS token, upload/manual/statement, demo buttons) → **Review** (confirm or reject, suspicious mail) → **Bills**.

API docs: http://localhost:8000/docs · Health: http://localhost:8000/api/health (shows connector modes and any missing variables).

Tests: `cd backend && python -m pytest` (62 tests).

## The pipeline (`backend/app/services/pipeline.py`)

Every input goes through one path:

```
hash/dedup → prefilter (OTP dropped, nothing stored) → redact → extract A (LLM) + B (rules)
→ reconcile → trust check → decide:
     suspicious                       → flagged_items (no obligation)
     not a bill                       → dropped
     mismatch / low confidence / new biller / medium trust / missing fields → pending confirmation
     receipt or debit                 → mark a matching bill paid, record the charge, detect recurring
     otherwise                        → create the obligation, or merge it into an existing one
```

- The raw text exists only in memory. `ingest_events` store a hash and an outcome. OTP events don't even store the hash. A test scans the SQLite file to check this.
- When the two extractors disagree on an amount or date, the pipeline never picks one. The confirmation holds both values, and resolving it returns a 422 until the user chooses.
- The first bill from a biller you have no history with always goes to confirmation (`NEW_BILLER`). Uploads skip this check because you sent the file yourself.

## Endpoints (all under `/api`)

| Area | Endpoints |
|---|---|
| Auth/profile | `POST auth/register`, `POST auth/login`, `GET auth/me`, `GET/PUT profile` |
| Sources | `GET sources`, `GET sources/gmail/connect`, `GET sources/gmail/callback`, `POST sources/gmail/sync`, `DELETE sources/gmail`, `POST sources/sms/token`, `DELETE sources/sms`, `PUT sources/whatsapp` |
| Ingest | `POST ingest/sms` (X-Ingest-Token), `POST webhooks/twilio/whatsapp` (Twilio signature), `POST ingest/upload`, `POST ingest/manual`, `POST ingest/statement` |
| Review | `GET obligations`, `GET obligations/{id}`, `GET confirmations`, `POST confirmations/{id}/resolve`, `GET flagged`, `POST flagged/{id}/dismiss`, `GET ingest-events` |
| Demo | `GET demo/fixtures`, `POST demo/simulate/{sms,email,whatsapp,fake-email}` (fixtures go through the real pipeline and are labelled DEMO) |

## Implementation decisions (not fixed by the spec)

- Google OAuth and the Gmail REST API are called with `httpx` instead of google-api-python-client. The surface is small and easy to mock.
- Passwords are hashed with `bcrypt` directly, not passlib, which is unmaintained.
- SMS ingest tokens look like `<prefix>.<secret>`. Only the SHA-256 is stored, and comparison is constant-time.
- The mock LLM is a separate heuristic from the rules extractor. Tags like `[mock:amount=899]`, `[mock:llm-fail]` and `[mock:llm-invalid]` exercise the mismatch and failure paths.
- In live mode the LLM uses structured JSON output with `effort: low`, and the model comes from `ANTHROPIC_MODEL`. For models that support it, the server-side refusal fallback is enabled.
- WhatsApp `PAID` / `15` / `30` are recognised but only acknowledged, because they act on reminders, which are output side. `HELP` and `WHAT'S DUE` work.
- Enums are stored as strings. Tables are created on startup and there are no Alembic migrations yet.

## Human setup for live connectors

See `docs/SETUP_HUMAN_STEPS.md`.
