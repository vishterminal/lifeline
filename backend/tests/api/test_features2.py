"""Monthly report, documents vault, bill splits, Ask Lifeline, regional-language bills,
photo-text ingest, web push endpoints, WhatsApp questions."""
from datetime import date, timedelta

from app.config import get_settings
from app.db import SessionLocal


def _add(client, h, **kw):
    r = client.post("/api/ingest/manual", json=kw, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["obligation"]["id"]


def _d(n):
    return (date.today() + timedelta(days=n)).isoformat()


def test_monthly_report_counts_penalties_avoided(client, user):
    h, _ = user
    a = _add(client, h, biller="Bike insurance", type="INSURANCE_VEHICLE", amount=2150, due_date=_d(10))
    b = _add(client, h, biller="TNEB", type="ELECTRICITY", amount=1840, due_date=_d(3))
    client.post(f"/api/obligations/{a}/pay-mock", headers=h)
    client.post(f"/api/obligations/{b}/mark-paid", headers=h)
    r = client.get("/api/report", headers=h).json()
    assert r["paid_count"] == 2 and r["paid_on_time"] == 2
    assert r["penalties_avoided"] == "5050"  # insurance lapse 5000 + electricity late fee 50 (estimated)
    assert client.get("/api/report?month=2026-13", headers=h).status_code == 422


def test_documents_vault_creates_tracked_renewal_and_chain(client, user):
    h, _ = user
    puc = client.post("/api/documents", json={"kind": "PUC", "label": "PUC certificate", "number": "PUC/TN/88231",
                                               "vehicle_ref": "TN 09 AB 1234", "expiry_date": _d(5)}, headers=h).json()
    assert puc["number_last4"] == "8231" and puc["vehicle_ref"] == "TN09AB1234" and puc["days_left"] == 5
    client.post("/api/documents", json={"kind": "INSURANCE_VEHICLE", "label": "Bike insurance", "vehicle_ref": "TN09AB1234",
                                        "expiry_date": _d(20)}, headers=h)
    rows = {r["biller_raw"]: r for r in client.get("/api/bills", headers=h).json()}
    assert "insurance renewal will be blocked" in rows["PUC certificate"]["chain_hint"]
    assert client.delete(f"/api/documents/{puc['id']}", headers=h).json()["status"] == "removed"
    assert len(client.get("/api/documents", headers=h).json()) == 1
    bad = client.post("/api/documents", json={"kind": "NOPE", "label": "x", "expiry_date": _d(5)}, headers=h)
    assert bad.status_code == 422


def test_bill_split_equal_shares_paid_and_remind(client, user):
    h, _ = user
    oid = _add(client, h, biller="Airtel fibre", type="PHONE_INTERNET", amount=1200, due_date=_d(6))
    r = client.post(f"/api/obligations/{oid}/splits", json={"people": [{"name": "Arun", "phone_e164": "+919811100011"},
                                                                          {"name": "Priya"}], "include_me": True}, headers=h).json()
    assert [s["share_amount"] for s in r["shares"]] == ["400.00", "400.00"] and r["my_share"] == "400.00"
    assert r["others_owe"] == "800.00"
    sid = r["shares"][0]["id"]
    rem = client.post(f"/api/splits/{sid}/remind", headers=h).json()
    assert rem["status"] == "SIMULATED" and "Arun" in rem["message"] and "₹400.00" in rem["message"]
    assert client.post(f"/api/splits/{sid}/paid", headers=h).json()["others_owe"] == "400.00"
    other = {"Authorization": "Bearer " + client.post("/api/auth/demo").json()["token"]}
    assert client.post(f"/api/splits/{sid}/paid", headers=other).status_code == 404
    assert client.post(f"/api/obligations/{oid}/splits", json={"people": [{"name": "X", "phone_e164": "123"}]}, headers=h).status_code == 422


def test_ask_lifeline_intents(client, user):
    h, _ = user
    assert "no open bills" in client.post("/api/ask", json={"question": "what do I owe?"}, headers=h).json()["answer"]
    _add(client, h, biller="TNEB", type="ELECTRICITY", amount=1840, due_date=_d(2))
    _add(client, h, biller="Bike insurance", type="INSURANCE_VEHICLE", amount=2150, due_date=_d(20))
    _add(client, h, biller="Netflix", amount=649, due_date=_d(12), recurring="MONTHLY")
    _add(client, h, biller="BESCOM", type="ELECTRICITY", amount=900, due_date=_d(-2))
    ask = lambda q: client.post("/api/ask", json={"question": q}, headers=h).json()  # noqa: E731
    assert ask("What do I owe this week?")["intent"] == "window" and "TNEB" in ask("What do I owe this week?")["answer"]
    assert ask("What's most urgent?")["answer"].split("\n")[1].startswith("• Bike insurance")
    assert "BESCOM" in ask("Anything overdue?")["answer"]
    assert "649" in ask("How much do subscriptions cost me?")["answer"]
    assert "Settings" in ask("Can I afford my bills before salary?")["answer"]
    client.put("/api/profile", json={"balance_amount": 1000}, headers=h)
    assert ask("Can I afford my bills?")["answer"].startswith("Not quite")
    assert "Netflix" in ask("When is my Netflix due?")["answer"]
    assert ask("sing me a song")["intent"] == "help"


def test_hindi_and_tamil_bills_are_understood(client, user):
    h, _ = user
    r = client.post("/api/demo/simulate/sms", json={"fixture": "hindi"}, headers=h).json()
    assert r["outcome"] in ("NEEDS_CONFIRMATION", "SAVED")
    conf = client.get("/api/confirmations", headers=h).json()[0]["draft"]["fields"]
    assert conf["amount"] == "599.00" and conf["type"] == "PHONE_INTERNET"
    t = client.post("/api/demo/simulate/sms", json={"text": f"உங்கள் மின் கட்டணம் ரூ. 1,250 செலுத்த கடைசி தேதி {(date.today() + timedelta(days=9)).strftime('%d %b %Y')}."}, headers=h).json()
    assert t["outcome"] in ("NEEDS_CONFIRMATION", "SAVED")
    otp = client.post("/api/demo/simulate/sms", json={"text": "आपका ओटीपी 482913 है। किसी से साझा न करें।"}, headers=h).json()
    assert otp["outcome"] == "DROPPED_OTP"


def test_text_from_photo_goes_through_pipeline(client, user):
    h, _ = user
    txt = f"BESCOM electricity bill Rs. 2,310.00 due on {(date.today() + timedelta(days=12)).strftime('%d %b %Y')}"
    r = client.post("/api/ingest/text", json={"text": txt}, headers=h).json()
    assert r["outcome"] == "SAVED"  # user-supplied: no new-biller question
    assert client.post("/api/ingest/text", json={"text": "hi"}, headers=h).status_code == 422


def test_push_endpoints(client, user, monkeypatch):
    h, _ = user
    assert client.get("/api/push/vapid-public-key").json()["enabled"] is False
    assert client.post("/api/push/test", headers=h).status_code == 409
    sub = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": {"p256dh": "k" * 20, "auth": "a" * 10}}
    assert client.post("/api/push/subscribe", json=sub, headers=h).status_code == 201
    assert client.post("/api/push/subscribe", json={**sub, "endpoint": "http://evil"}, headers=h).status_code == 422
    assert client.get("/api/push/status", headers=h).json()["subscriptions"] == 1
    # with keys configured, a reminder tick calls the push sender
    from app.services import push_service

    sent = []
    monkeypatch.setattr(get_settings(), "vapid_public_key", "pub")
    monkeypatch.setattr(get_settings(), "vapid_private_key", "priv")
    monkeypatch.setattr(push_service, "send", lambda db, u, t, b, url="/": sent.append(b) or 1)
    from app.services import reminder_service

    monkeypatch.setattr(reminder_service, "in_quiet_hours", lambda u, now: False)  # any time of day
    _add(client, h, biller="Bike insurance", type="INSURANCE_VEHICLE", amount=2150, due_date=_d(3))
    client.post("/api/reminders/tick", headers=h)
    assert sent and "Bike insurance" in sent[0]


def test_whatsapp_question_gets_an_answer(client, user):
    from app.services import whatsapp_inbound

    h, _ = user
    client.put("/api/sources/whatsapp", json={"phone_e164": "+919800000888"}, headers=h)
    _add(client, h, biller="TNEB", type="ELECTRICITY", amount=1840, due_date=_d(1))
    with SessionLocal() as db:
        reply = whatsapp_inbound.handle_inbound(db, {"From": "whatsapp:+919800000888", "Body": "What do I owe this week?"})
        db.commit()
    assert "TNEB" in reply and "₹1,840" in reply


def test_whatsapp_personal_question_is_not_treated_as_bill_question(client, user):
    from app.services import whatsapp_inbound

    h, _ = user
    client.put("/api/sources/whatsapp", json={"phone_e164": "+919800000889"}, headers=h)
    with SessionLocal() as db:
        reply = whatsapp_inbound.handle_inbound(db, {"From": "whatsapp:+919800000889", "Body": "Hey, dinner tonight?"})
        db.commit()
    assert "doesn't look like a bill" in reply
