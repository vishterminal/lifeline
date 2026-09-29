"""AutoPay pre-debit warning + "Still using it?", and the bill-shock alert."""
from datetime import date, datetime, time, timedelta

from app.db import SessionLocal
from app.models import Obligation, User
from app.services import reminder_service, risk_service
from app.timeutil import tz


def _d(n):
    return (date.today() + timedelta(days=n)).isoformat()


def _confirm_all(client, h):
    for c in client.get("/api/confirmations", headers=h).json():
        r = client.post(f"/api/confirmations/{c['id']}/resolve", json={"action": "confirm"}, headers=h)
        assert r.status_code == 200, r.text


def test_predebit_sms_is_an_autopay_renewal_not_a_payment(client, user):
    h, _ = user
    r = client.post("/api/demo/simulate/sms", json={"fixture": "predebit"}, headers=h).json()
    assert r["outcome"] in ("NEEDS_CONFIRMATION", "SAVED")
    _confirm_all(client, h)
    subs = client.get("/api/subscriptions", headers=h).json()
    row = next(s for s in subs["subscriptions"] if s["biller"] == "Netflix")
    assert row["autopay"] is True and row["amount"] == "649.00" and row["next_renewal"] == _d(1)
    assert subs["autopay_count"] == 1


def test_predebit_updates_known_subscription_and_flags_price_change(client, user):
    h, _ = user
    oid = client.post("/api/ingest/manual", json={"biller": "Netflix", "amount": 499, "due_date": _d(1),
                                                   "recurring": "MONTHLY"}, headers=h).json()["obligation"]["id"]
    r = client.post("/api/demo/simulate/sms", json={"fixture": "predebit"}, headers=h).json()
    assert r["outcome"] == "SAVED" and r["reason"] == "autopay_predebit" and r["obligation_id"] == oid
    o = client.get(f"/api/obligations/{oid}", headers=h).json()
    assert o["autopay"] is True and o["amount"] == "649.00" and o["price_changed"] is True


def test_still_using_it_answer_and_savings(client, user):
    h, _ = user
    oid = client.post("/api/ingest/manual", json={"biller": "Netflix", "amount": 649, "due_date": _d(4),
                                                   "recurring": "MONTHLY"}, headers=h).json()["obligation"]["id"]
    assert client.post(f"/api/subscriptions/{oid}/usage", json={"using": False}, headers=h).json()["usage"] == "NOT_USING"
    subs = client.get("/api/subscriptions", headers=h).json()
    assert subs["potential_savings_yearly"] == "7788"  # 649 x 12
    assert client.post(f"/api/subscriptions/{oid}/usage", json={"using": True}, headers=h).json()["usage"] == "USING"
    assert client.get("/api/subscriptions", headers=h).json()["potential_savings_yearly"] == "0"
    bill = client.post("/api/ingest/manual", json={"biller": "TNEB", "type": "ELECTRICITY", "amount": 900,
                                                    "due_date": _d(4)}, headers=h).json()["obligation"]["id"]
    assert client.post(f"/api/subscriptions/{bill}/usage", json={"using": False}, headers=h).status_code == 409


def test_autopay_reminder_wording(client, user):
    _, u = user
    with SessionLocal() as db:
        o = Obligation(user_id=u["id"], type="SUBSCRIPTION", biller_raw="Netflix", biller_norm="netflix", amount=649,
                       due_date=date.today() + timedelta(days=1), is_recurring=True, autopay=True, fingerprint="x")
        c = risk_service.assess(o, [o], date.today())
        text = reminder_service.message_for(o, c, 1)
        assert text.startswith("⚡ AutoPay: Netflix will charge ₹649 automatically tomorrow") and "Still using it?" in text
        o.usage = "NOT_USING"
        assert "not using it" in reminder_service.message_for(o, c, 1)


def test_bill_shock_alert(client, user):
    h, _ = user
    client.post("/api/ingest/manual", json={"biller": "TNEB", "type": "ELECTRICITY", "amount": 1800, "due_date": _d(-40)}, headers=h)
    client.post("/api/ingest/manual", json={"biller": "TNEB", "type": "ELECTRICITY", "amount": 1840, "due_date": _d(1)}, headers=h)
    client.post("/api/ingest/manual", json={"biller": "TNEB", "type": "ELECTRICITY", "amount": 2950, "due_date": _d(30)}, headers=h)
    rows = {r["amount"]: r for r in client.get("/api/bills", headers=h).json()}
    s = rows["2950.00"]["shock"]
    assert s["pct"] == 62 and s["usual"] == "1820.00" and s["based_on"] == 2 and len(s["history"]) == 3
    assert rows["1840.00"]["shock"] is None  # +2% is normal
    assert rows["1800.00"]["shock"] is None  # nothing earlier to compare


def test_bill_shock_in_reminder_text(client, user):
    _, u = user
    with SessionLocal() as db:
        a = Obligation(user_id=u["id"], type="ELECTRICITY", biller_raw="TNEB", biller_norm="tneb", amount=1000,
                       due_date=date.today() - timedelta(days=30), status="PAID", fingerprint="a")
        b = Obligation(user_id=u["id"], type="ELECTRICITY", biller_raw="TNEB", biller_norm="tneb", amount=1600,
                       due_date=date.today() + timedelta(days=1), fingerprint="b")
        db.add_all([a, b])
        db.commit()
        noon = datetime.combine(date.today(), time(12, 0), tzinfo=tz())  # outside quiet hours
        reminder_service.tick(db, db.get(User, u["id"]), noon)
        db.commit()
    feed = [r["message"] for r in client.get("/api/reminders", headers=user[0]).json()]
    assert any("60% higher than your usual ₹1,000" in m for m in feed)
