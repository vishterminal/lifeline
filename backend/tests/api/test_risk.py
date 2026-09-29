"""₹-risk ranking, obligation chain (PUC -> insurance), what-if, and bill actions."""
from datetime import date, timedelta

import pytest

from app.services import risk_service


def _add(client, h, **kw):
    r = client.post("/api/ingest/manual", json=kw, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["obligation"]["id"]


def _d(n):
    return (date.today() + timedelta(days=n)).isoformat()


def test_big_risk_outranks_small_bill_due_sooner(client, user):
    h, _ = user
    elec = _add(client, h, biller="TNEB", type="ELECTRICITY", amount=1840, due_date=_d(1))
    ins = _add(client, h, biller="Bike insurance", type="INSURANCE_VEHICLE", amount=2150, due_date=_d(21), vehicle_ref="TN09AB1234")
    rows = client.get("/api/bills", headers=h).json()
    assert [r["id"] for r in rows[:2]] == [ins, elec]  # ₹5,000-class lapse beats a ₹50 late fee due tomorrow
    by = {r["id"]: r["consequence"] for r in rows}
    assert by[elec]["total"] == "50" and by[elec]["tier"] == "LOW"
    assert by[ins]["tier"] == "HIGH"
    # Seeded placeholder numbers are never shown as Verified
    assert by[elec]["label"] == "ESTIMATED" and by[ins]["label"] == "ESTIMATED"
    by_date = client.get("/api/bills?sort=date", headers=h).json()
    assert by_date[0]["id"] == elec


def test_puc_blocks_insurance_chain_and_whatif(client, user):
    h, _ = user
    puc = _add(client, h, biller="PUC certificate", type="PUC", due_date=_d(5), vehicle_ref="TN09AB1234")
    ins = _add(client, h, biller="Bike insurance", type="INSURANCE_VEHICLE", amount=2150, due_date=_d(21), vehicle_ref="TN09AB1234")
    rows = {r["id"]: r for r in client.get("/api/bills", headers=h).json()}
    assert "insurance renewal will be blocked" in rows[puc]["chain_hint"]
    assert rows[puc]["consequence"]["downstream"] == "6000"  # insurance lapse 5000 + compliance 2000 x 0.5
    assert rows[ins]["chain_hint"].startswith("Needs a valid PUC certificate")

    ch = client.get(f"/api/obligations/{puc}/chain", headers=h).json()
    assert ch["downstream"][0]["obligation_id"] == ins and ch["downstream"][0]["relation"] == "BLOCKS_RENEWAL"
    wi = client.get(f"/api/obligations/{puc}/whatif", headers=h).json()
    assert wi["total"] == "7000" and len(wi["timeline_effects"]) >= 2


def test_multi_vehicle_needs_matching_vehicle_ref(client, user):
    h, _ = user
    puc = _add(client, h, biller="PUC", type="PUC", due_date=_d(5), vehicle_ref="TN09AB1234")
    _add(client, h, biller="Car insurance", type="INSURANCE_VEHICLE", amount=9000, due_date=_d(20), vehicle_ref="KA01XY9999")
    rows = {r["id"]: r for r in client.get("/api/bills", headers=h).json()}
    assert rows[puc]["chain_hint"] is None  # different vehicle: not linked


def test_mock_pay_and_actions(client, user):
    h, _ = user
    a = _add(client, h, biller="TNEB", type="ELECTRICITY", amount=1840, due_date=_d(1))
    r = client.post(f"/api/obligations/{a}/pay-mock", headers=h).json()
    assert r["payment"]["is_mock"] is True and r["obligation"]["status"] == "PAID" and r["obligation"]["paid_via"] == "MOCK"
    assert client.post(f"/api/obligations/{a}/pay-mock", headers=h).status_code == 409
    b = _add(client, h, biller="Airtel", type="PHONE_INTERNET", amount=799, due_date=_d(9))
    assert client.post(f"/api/obligations/{b}/snooze", json={"minutes": 30}, headers=h).status_code == 200
    assert client.post(f"/api/obligations/{b}/dismiss", headers=h).json()["status"] == "DISMISSED"
    c = _add(client, h, biller="Jio", type="PHONE_INTERNET", amount=399, due_date=_d(3))
    assert client.post(f"/api/obligations/{c}/mark-paid", headers=h).json()["paid_via"] == "USER_MARKED"


def test_other_users_bills_are_invisible(client, user):
    h, _ = user
    a = _add(client, h, biller="TNEB", type="ELECTRICITY", amount=100, due_date=_d(1))
    h2 = {"Authorization": "Bearer " + client.post("/api/auth/demo").json()["token"]}
    assert client.post(f"/api/obligations/{a}/pay-mock", headers=h2).status_code == 404
    assert client.get(f"/api/obligations/{a}/whatif", headers=h2).status_code == 404


def test_verified_without_source_is_rejected(monkeypatch, tmp_path):
    bad = tmp_path / "penalty_rules_seed.json"
    bad.write_text('{"rules":[{"obligation_type":"PUC","lapse_cost":1,"verification":"VERIFIED","source_label":"PLACEHOLDER x"}]}')
    monkeypatch.setattr(risk_service, "DATA_DIR", tmp_path)
    risk_service.penalty_rules.cache_clear()
    with pytest.raises(risk_service.RuleError):
        risk_service.penalty_rules()
    monkeypatch.undo()
    risk_service.penalty_rules.cache_clear()
