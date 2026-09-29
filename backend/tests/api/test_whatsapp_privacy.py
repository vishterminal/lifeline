from datetime import date, timedelta

import pytest
from twilio.request_validator import RequestValidator

from app.config import get_settings
from app.services import whatsapp_inbound

URL = "https://lifeline.test/api/webhooks/twilio/whatsapp"


@pytest.fixture
def twilio_token(monkeypatch):
    monkeypatch.setattr(get_settings(), "twilio_auth_token", "twilio-test-token")
    return "twilio-test-token"


def _post(client, params, token=None, sig=None):
    headers = {}
    if token:
        headers["X-Twilio-Signature"] = sig or RequestValidator(token).compute_signature(URL, params)
    return client.post("/api/webhooks/twilio/whatsapp", data=params, headers=headers)


def test_signature_invalid_rejected(client, twilio_token):
    r = _post(client, {"From": "whatsapp:+919800000001", "Body": "hi"}, twilio_token, sig="bogus")
    assert r.status_code == 403
    assert client.post("/api/webhooks/twilio/whatsapp", data={"Body": "x"}).status_code == 403


def test_unknown_number_gets_link_hint(client, twilio_token):
    r = _post(client, {"From": "whatsapp:+919800000002", "Body": "bill due"}, twilio_token)
    assert r.status_code == 200 and "isn't linked" in r.text


def test_forwarded_text_and_commands(client, user, twilio_token):
    h, _ = user
    client.put("/api/sources/whatsapp", json={"phone_e164": "+919800000003"}, headers=h)
    due = (date.today() + timedelta(days=6)).strftime("%d %b %Y")
    r = _post(client, {"From": "whatsapp:+919800000003", "Body": f"Fwd: Airtel postpaid bill Rs 799 due on {due}",
                       "NumMedia": "0"}, twilio_token)
    assert r.status_code == 200 and "<Message>" in r.text and "confirmation" in r.text
    prof = client.get("/api/profile", headers=h).json()
    assert prof["whatsapp_last_inbound_at"]  # 24h window tracked
    wa = [s for s in client.get("/api/sources", headers=h).json() if s["kind"] == "WHATSAPP"][0]
    assert wa["window_open"] and wa["status"] == "CONNECTED"
    assert "Commands" in _post(client, {"From": "whatsapp:+919800000003", "Body": "HELP"}, twilio_token).text
    assert "Nothing due" in _post(client, {"From": "whatsapp:+919800000003", "Body": "WHAT'S DUE"}, twilio_token).text
    assert "reminders are switched on" in _post(client, {"From": "whatsapp:+919800000003", "Body": "PAID"}, twilio_token).text


def test_forwarded_media_goes_to_upload(client, db, user):
    from app.models import User

    h, _ = user
    client.put("/api/sources/whatsapp", json={"phone_e164": "+919800000004"}, headers=h)
    fetched = []

    def fake_fetch(url):
        fetched.append(url)
        return b"\xff\xd8\xff" + b"\x00" * 50, "image/jpeg"

    reply = whatsapp_inbound.handle_inbound(db, {"From": "whatsapp:+919800000004", "Body": "", "NumMedia": "1",
                                                 "MediaUrl0": "https://api.twilio.com/media/1"}, media_fetcher=fake_fetch)
    db.commit()
    assert fetched and "type the details" in reply
    assert client.get("/api/confirmations", headers=h).json()[0]["reason"] == "MISSING_FIELDS"


def test_no_raw_content_persisted(client, user):
    """Scan the whole SQLite file for a unique marker from a message body."""
    from tests.conftest import DB_PATH

    h, _ = user
    marker = "ZQXMARKER9731"
    due = (date.today() + timedelta(days=3)).strftime("%d %b %Y")
    client.post("/api/demo/simulate/sms", json={"text": f"Jio bill Rs 399 due on {due}. Ref {marker}"}, headers=h)
    client.post("/api/demo/simulate/sms", json={"text": f"Your OTP is 123456 {marker}. Do not share."}, headers=h)
    client.post("/api/demo/simulate/fake-email", headers=h)
    assert marker.encode() not in DB_PATH.read_bytes()
    assert marker.lower().encode() not in DB_PATH.read_bytes()


def test_otp_event_stores_no_hash(client, user):
    h, _ = user
    client.post("/api/demo/simulate/sms", json={"fixture": "otp"}, headers=h)
    from app.db import SessionLocal
    from app.models import IngestEvent

    with SessionLocal() as s:
        ev = s.query(IngestEvent).filter_by(outcome="DROPPED_OTP").all()
        assert ev and all(e.content_hash == "" for e in ev)
