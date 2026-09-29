from datetime import date, timedelta
from decimal import Decimal

from app.models import ChargeEvent, User
from app.security import hash_password
from app.services import recurring_service, trust_service
from app.services.billers import all_aliases


def _user(db, email):
    u = User(email=email, password_hash=hash_password("password123"))
    db.add(u)
    db.flush()
    return u


def _alias(db, name):
    return next(a for a in all_aliases(db) if a.canonical_name == name)


PASS = "mx; dkim=pass; spf=pass; dmarc=pass"


def test_real_netflix_receipt_verified(db):
    u = _user(db, "trust1@example.com")
    today = date.today()
    db.add(ChargeEvent(user_id=u.id, charge_date=today - timedelta(days=30), merchant_norm="netflix",
                       amount=Decimal("649"), source="STATEMENT"))
    db.flush()
    r = trust_service.score(db, u.id, trust_service.TrustInput(
        source_kind="GMAIL", sender="info@mailer.netflix.com", auth_results=PASS, text="Payment received",
        alias=_alias(db, "netflix"), biller_norm="netflix", amount=Decimal("649"), event_date=today,
        message_kind="RECEIPT"), all_aliases(db))
    assert r.label == "VERIFIED_SENDER", r
    db.rollback()


def test_fake_netflix_suspicious(db):
    u = _user(db, "trust2@example.com")
    r = trust_service.score(db, u.id, trust_service.TrustInput(
        source_kind="GMAIL", sender="billing@netf1ix-billing.co", auth_results="dkim=fail; spf=softfail; dmarc=fail",
        links=[("http://netf1ix-billing.co/pay", "netflix.com")],
        text="Your Netflix payment is due. Pay now or your account will be suspended in 24 hours.",
        alias=_alias(db, "netflix"), biller_norm="netflix", amount=Decimal("2499"), message_kind="DUE_NOTICE"),
        all_aliases(db))
    assert r.label == "SUSPICIOUS" and r.score > 60
    db.rollback()


def test_unknown_biller_clean_headers_new_biller(db):
    u = _user(db, "trust3@example.com")
    r = trust_service.score(db, u.id, trust_service.TrustInput(
        source_kind="GMAIL", sender="bills@acme-water.example", auth_results=PASS, text="Water bill due",
        alias=None, biller_norm="acme_water", amount=Decimal("300"), message_kind="DUE_NOTICE"), all_aliases(db))
    assert r.label == "NEW_BILLER_CONFIRM"
    db.rollback()


def test_amount_4x_typical_raises_risk(db):
    u = _user(db, "trust4@example.com")
    today = date.today()
    db.add(ChargeEvent(user_id=u.id, charge_date=today - timedelta(days=30), merchant_norm="airtel",
                       amount=Decimal("500"), source="STATEMENT"))
    db.flush()
    base = dict(source_kind="SMS", sender="VM-AIRTEL", text="bill due", alias=_alias(db, "airtel"),
                biller_norm="airtel", event_date=today, message_kind="DUE_NOTICE")
    normal = trust_service.score(db, u.id, trust_service.TrustInput(amount=Decimal("500"), **base), all_aliases(db))
    high = trust_service.score(db, u.id, trust_service.TrustInput(amount=Decimal("2000"), **base), all_aliases(db))
    assert high.score > normal.score
    db.rollback()


def test_lookalike_detection(db):
    assert trust_service.is_lookalike("netf1ix-billing.co", all_aliases(db)).canonical_name == "netflix"
    assert trust_service.is_lookalike("mailer.netflix.com", all_aliases(db)) is None


def test_recurring_monthly_and_price_change(db):
    u = _user(db, "rec1@example.com")
    start = date.today() - timedelta(days=60)
    for i, amt in enumerate(["649", "649", "649"]):
        db.add(ChargeEvent(user_id=u.id, charge_date=start + timedelta(days=30 * i), merchant_norm="netflix",
                           amount=Decimal(amt), source="STATEMENT"))
    db.flush()
    sub = recurring_service.update_recurring(db, u.id, "netflix", "Netflix")
    assert sub.is_recurring and sub.recurrence_interval_days == 30
    assert sub.next_expected_date == start + timedelta(days=90) and not sub.price_changed
    db.add(ChargeEvent(user_id=u.id, charge_date=start + timedelta(days=90), merchant_norm="netflix",
                       amount=Decimal("799"), source="RECEIPT"))
    db.flush()
    sub2 = recurring_service.update_recurring(db, u.id, "netflix", "Netflix")
    assert sub2.id == sub.id and sub2.price_changed and sub2.amount == Decimal("799.00")
    db.rollback()
