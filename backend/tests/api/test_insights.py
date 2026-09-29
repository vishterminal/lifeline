"""Penalty Fighter, cash-flow planner, life-load, subscriptions, delete-all-my-data."""
from datetime import date, timedelta

from app.db import SessionLocal
from app.models import Obligation, User


def _add(client, h, **kw):
    r = client.post("/api/ingest/manual", json=kw, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["obligation"]["id"]


def _d(n):
    return (date.today() + timedelta(days=n)).isoformat()


def test_penalty_fighter_only_for_late_bills_and_uses_facts(client, user):
    h, _ = user
    on_time = _add(client, h, biller="TNEB", type="ELECTRICITY", amount=1840, due_date=_d(5))
    assert client.post(f"/api/obligations/{on_time}/waiver-draft", headers=h).status_code == 409
    late = _add(client, h, biller="BESCOM", type="ELECTRICITY", amount=2310, due_date=_d(-3))
    r = client.post(f"/api/obligations/{late}/waiver-draft", headers=h).json()
    t = r["text"]
    assert "BESCOM" in t and "Rs. 2,310.00" in t and "3 day(s) late" in t
    assert "[your account number]" in t  # never invents an account number
    assert len(t.split()) <= 150
    assert r["likelihood"].startswith("Unknown")
    assert client.patch(f"/api/waiver-drafts/{r['draft_id']}", json={"outcome": "GRANTED"}, headers=h).json()["outcome"] == "GRANTED"


def test_cashflow_needs_balance_then_warns_and_prioritises(client, user):
    h, _ = user
    _add(client, h, biller="TNEB", type="ELECTRICITY", amount=1840, due_date=_d(2))
    _add(client, h, biller="Bike insurance", type="INSURANCE_VEHICLE", amount=2150, due_date=_d(2), vehicle_ref="TN09AB1234")
    assert client.get("/api/cashflow/plan", headers=h).json()["needs_balance"] is True
    salary_day = (date.today() + timedelta(days=10)).day
    client.put("/api/profile", json={"balance_amount": 2500, "salary_day": salary_day, "salary_amount": 50000}, headers=h)
    p = client.get("/api/cashflow/plan", headers=h).json()
    statuses = {s["biller"]: s["status"] for s in p["schedule"]}
    # only one fits: the bill with the highest penalty per rupee (insurance lapse) is paid first
    assert statuses["Bike insurance"] == "PLANNED" and statuses["TNEB"] == "SHORT"
    assert any("Salary arrives after this due date" in w for w in p["warnings"])
    assert p["warnings"][0].startswith("Money is tight: pay Bike insurance first")
    assert len(p["balance_line"]) == 46 and any(x["salary"] for x in p["balance_line"])


def test_salary_day_31_in_short_month():
    from app.routers.insights import _salary_dates

    ds = _salary_dates(31, date(2026, 11, 1), date(2027, 1, 31))
    assert [d.isoformat() for d in ds] == ["2026-11-30", "2026-12-31", "2027-01-31"]


def test_lifeload(client, user):
    h, _ = user
    assert client.get("/api/lifeload", headers=h).json()["score"] == 0
    _add(client, h, biller="Bike insurance", type="INSURANCE_VEHICLE", amount=2150, due_date=_d(3))
    _add(client, h, biller="Airtel", type="PHONE_INTERNET", amount=799, due_date=_d(2))
    r = client.get("/api/lifeload", headers=h).json()
    assert r["score"] == (5 + 1) * 8 and r["label"] == "Moderate" and r["items_next_7_days"] == 2


def test_subscriptions_duplicates_and_yearly(client, user):
    h, _ = user
    _add(client, h, biller="Netflix", amount=649, due_date=_d(20), recurring="MONTHLY")
    _add(client, h, biller="Amazon Prime", amount=299, due_date=_d(12), recurring="MONTHLY")
    r = client.get("/api/subscriptions", headers=h).json()
    names = {s["biller"] for s in r["subscriptions"]}
    assert {"Netflix", "Amazon Prime"} <= names
    assert r["duplicates"] and r["duplicates"][0]["category"] == "Video Streaming"
    assert r["monthly_total"] == "948" and r["yearly_total"] == "11376"
    nf = next(s for s in r["subscriptions"] if s["biller"] == "Netflix")
    assert nf["manage_url"] == "https://www.netflix.com/account"


def test_delete_all_my_data(client):
    tok = client.post("/api/auth/register", json={"email": "wipe.me@example.com", "password": "password123"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    _add(client, h, biller="TNEB", type="ELECTRICITY", amount=100, due_date=_d(3))
    client.post("/api/family", json={"name": "A", "phone_e164": "+919811100001", "consented": True}, headers=h)
    assert client.request("DELETE", "/api/me/data", json={"confirm": "nope"}, headers=h).status_code == 422
    assert client.request("DELETE", "/api/me/data", json={"confirm": "DELETE"}, headers=h).json()["status"] == "deleted"
    with SessionLocal() as db:
        assert db.query(User).filter_by(email="wipe.me@example.com").count() == 0
        assert db.query(Obligation).filter(Obligation.biller_raw == "TNEB", Obligation.amount == 100).count() == 0
    assert client.get("/api/auth/me", headers=h).status_code == 401
