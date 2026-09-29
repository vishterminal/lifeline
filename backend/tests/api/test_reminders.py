"""Reminder & escalation engine: ladder by ₹ risk, cap, quiet hours, snooze, stop-on-paid,
WhatsApp window, family alert, WhatsApp PAID/15/30 replies."""
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Obligation, Reminder, User
from app.services import reminder_service
from app.timeutil import tz


def _add(client, h, **kw):
    r = client.post("/api/ingest/manual", json=kw, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["obligation"]["id"]


def _d(n):
    return (date.today() + timedelta(days=n)).isoformat()


def _at(days_from_today, hh):
    return datetime.combine(date.today() + timedelta(days=days_from_today), time(hh, 0), tzinfo=tz()).astimezone(timezone.utc)


def _user(db, h):
    from app.security import decode_jwt

    return db.get(User, decode_jwt(h["Authorization"][7:]))


def test_ladder_follows_risk_tier(client, user):
    h, _ = user
    low = _add(client, h, biller="Airtel", type="PHONE_INTERNET", amount=799, due_date=_d(7))  # LOW (₹100 fee)
    high = _add(client, h, biller="Bike insurance", type="INSURANCE_VEHICLE", amount=2150, due_date=_d(7))  # HIGH
    with SessionLocal() as db:
        u = _user(db, h)
        r = reminder_service.tick(db, u, _at(0, 10))
        db.commit()
        rows = list(db.scalars(select(Reminder).where(Reminder.user_id == u.id)))
        by = {}
        for row in rows:
            by.setdefault(row.obligation_id, set()).add(row.channel)
        assert by[low] == {"IN_APP", "PUSH"} and by[high] == {"IN_APP", "PUSH"}  # both at T-7
        # the same tick again is idempotent
        assert reminder_service.tick(db, u, _at(0, 10)).sent == 0


def test_high_risk_escalates_to_whatsapp_repeats_to_cap_then_family(client, user):
    h, _ = user
    client.post("/api/family", json={"name": "Amma", "phone_e164": "+919811100099", "consented": True}, headers=h)
    oid = _add(client, h, biller="Bike insurance", type="INSURANCE_VEHICLE", amount=2150, due_date=_d(1))
    with SessionLocal() as db:
        u = _user(db, h)
        for hh in (9, 12, 15, 18):  # T-1: first send + repeats every 3 h, capped at 3, then family alert
            reminder_service.tick(db, u, _at(0, hh))
        db.commit()
        rows = [r for r in db.scalars(select(Reminder).where(Reminder.obligation_id == oid))]
        in_app = [r for r in rows if r.channel == "IN_APP"]
        assert len(in_app) == 3  # cap
        assert any(r.channel == "WHATSAPP" for r in rows)
        fam = [r for r in rows if r.channel == "FAMILY_WHATSAPP"]
        assert len(fam) == 1 and "Amma" not in fam[0].message


def test_quiet_hours_hold_reminders(client, user):
    h, _ = user
    _add(client, h, biller="Bike insurance", type="INSURANCE_VEHICLE", amount=2150, due_date=_d(1))
    with SessionLocal() as db:
        u = _user(db, h)
        res = reminder_service.tick(db, u, _at(0, 22))  # 22:00 IST
        assert res.sent == 0 and res.skipped == 1


def test_snooze_and_paid_stop_reminders(client, user, monkeypatch):
    monkeypatch.setattr(reminder_service, "in_quiet_hours", lambda u, now: False)  # any time of day
    h, _ = user
    oid = _add(client, h, biller="Bike insurance", type="INSURANCE_VEHICLE", amount=2150, due_date=_d(1))
    client.post(f"/api/obligations/{oid}/snooze", json={"minutes": 30}, headers=h)
    assert client.post("/api/reminders/tick", headers=h).json()["sent"] == 0  # snoozed
    with SessionLocal() as db:
        o = db.get(Obligation, oid); o.snoozed_until = None; db.commit()
    assert client.post("/api/reminders/tick", headers=h).json()["sent"] >= 1
    client.post(f"/api/obligations/{oid}/mark-paid", headers=h)
    assert client.post("/api/reminders/tick", headers=h).json() == {"sent": 0, "simulated": 0, "skipped": 0, "family": 0}
    feed = client.get("/api/reminders", headers=h).json()
    assert feed and all(r["ack_type"] == "PAID" for r in feed if not r["simulated"])


def test_overdue_single_nudge(client, user):
    h, _ = user
    _add(client, h, biller="BESCOM", type="ELECTRICITY", amount=2310, due_date=_d(-3))
    assert client.post("/api/reminders/tick", headers=h).json()["sent"] == 1
    assert client.post("/api/reminders/tick", headers=h).json()["sent"] == 0


def test_simulate_next_days_and_clear(client, user):
    h, _ = user
    _add(client, h, biller="Bike insurance", type="INSURANCE_VEHICLE", amount=2150, due_date=_d(5))
    _add(client, h, biller="Airtel", type="PHONE_INTERNET", amount=799, due_date=_d(2))
    r = client.post("/api/reminders/simulate", json={"days": 7}, headers=h).json()
    assert len(r["days"]) == 7 and r["total"]["sent"] > 0
    assert any(x["simulated"] for x in client.get("/api/reminders", headers=h).json())
    assert client.delete("/api/reminders/simulated", headers=h).json()["removed"] > 0
    assert client.post("/api/reminders/simulate", json={"days": 99}, headers=h).status_code == 422


def test_whatsapp_replies_act_on_latest_reminder(client, user):
    from app.services import whatsapp_inbound

    h, _ = user
    client.put("/api/sources/whatsapp", json={"phone_e164": "+919800000777"}, headers=h)
    oid = _add(client, h, biller="TNEB", type="ELECTRICITY", amount=1840, due_date=_d(1))
    client.post("/api/reminders/tick", headers=h)
    with SessionLocal() as db:
        reply = whatsapp_inbound.handle_inbound(db, {"From": "whatsapp:+919800000777", "Body": "15"})
        db.commit()
        assert "15 minutes" in reply
        reply = whatsapp_inbound.handle_inbound(db, {"From": "whatsapp:+919800000777", "Body": "PAID"})
        db.commit()
        assert "Marked TNEB" in reply and db.get(Obligation, oid).status == "PAID"


def test_family_requires_consent_and_ownership(client, user):
    h, _ = user
    assert client.post("/api/family", json={"name": "X", "phone_e164": "+919811100098", "consented": False}, headers=h).status_code == 422
    assert client.post("/api/family", json={"name": "X", "phone_e164": "12345", "consented": True}, headers=h).status_code == 422
    fid = client.post("/api/family", json={"name": "Appa", "phone_e164": "+919811100097", "consented": True}, headers=h).json()["id"]
    other = {"Authorization": "Bearer " + client.post("/api/auth/demo").json()["token"]}
    assert client.delete(f"/api/family/{fid}", headers=other).status_code == 404
    assert client.delete(f"/api/family/{fid}", headers=h).json()["status"] == "removed"
