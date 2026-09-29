# Human setup — input connectors

Everything runs in mock mode without these steps. Do them only for live demos.

1. **Gmail (Google Cloud):** create a project and enable the Gmail API. On the OAuth consent screen choose **External, Testing**, and add the team's dummy Gmail accounts as test users. Create a web OAuth client with redirect URI `http://localhost:8000/api/sources/gmail/callback` plus the deployed URL. In `.env` set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `TOKEN_ENCRYPTION_KEY` and `CONNECTOR_MODE=live`. Testing-mode tokens expire after about 7 days, so reconnect the day before the demo. Expect the "unverified app" warning.
2. **Public URL:** run `ngrok http 8000` or `cloudflared tunnel --url http://localhost:8000` and set `PUBLIC_BASE_URL` to that URL. Free tunnel URLs change on restart, so update Twilio and the forwarder whenever that happens.
3. **Twilio WhatsApp sandbox:** open the sandbox and note the number and join code. Each phone sends the join code once. Set the inbound webhook to `<PUBLIC_BASE_URL>/api/webhooks/twilio/whatsapp` (POST). In `.env` set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` and `TWILIO_WHATSAPP_FROM`. In the app, link your number under Sources → WhatsApp (`PUT /api/sources/whatsapp`).
4. **SMS forwarder (Android):** install a free forwarder app and grant it SMS permission. Filter for bank, utility and telecom senders plus the words due, bill, debited, renewal and premium, and **exclude OTP**. Set the action to HTTP POST JSON `{"sender","text","received_at"}` to `<PUBLIC_BASE_URL>/api/ingest/sms`, with header `X-Ingest-Token` taken from `POST /api/sources/sms/token`. Turn off battery optimisation for the app.
5. **Anthropic:** set `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` and `LLM_MODE=live`.
6. **Optional local OCR:** install Tesseract so photos are read on-device before redaction. Without it, photos need the `allow_cloud_image_processing` consent, or the user types the details.
7. **Reference data:** `backend/app/data/biller_aliases_seed.json` only has official domains for Netflix. Before the trust check can mark any other biller "Verified sender", fill in real domains and sender IDs and set `reference_verified: true`.
