"""'What if my friend sends a mail with the exact bill keywords?'"""
from datetime import date, timedelta
from decimal import Decimal

from app.models import ChargeEvent, ConnectedSource, User
from app.security import hash_password
from app.services import trust_service
from app.services.billers import all_aliases
from app.services.pipeline import effective_kind

PASS = "mx.google.com; dkim=pass; spf=pass; dmarc=pass"  # a friend's real Gmail passes auth too


def _user(db, email, gmail=None):
    u = User(email=email, password_hash=hash_password("password123"))
    db.add(u)
    db.flush()
    if gmail:
        db.add(ConnectedSource(user_id=u.id, kind="GMAIL", status="CONNECTED", gmail_address=gmail))
        db.flush()
    return u


def _alias(db, name):
    return next(a for a in all_aliases(db) if a.canonical_name == name)


def _score(db, u, **kw):
    base = dict(source_kind="GMAIL", auth_results=PASS, text="Your bill is due", message_kind="DUE_NOTICE",
                amount=Decimal("649"))
    base.update(kw)
    return trust_service.score(db, u.id, trust_service.TrustInput(**base), all_aliases(db))


def test_friend_pretending_to_be_netflix_is_suspicious(db):
    u = _user(db, "f1@example.com")
    r = _score(db, u, sender="rahul.friend@gmail.com", alias=_alias(db, "netflix"), biller_norm="netflix")
    assert r.label == "SUSPICIOUS", r
    assert any("personal gmail.com" in x for x in r.reasons)
    db.rollback()


def test_friend_inventing_unknown_biller_is_suspicious(db):
    u = _user(db, "f2@example.com")
    r = _score(db, u, sender="rahul.friend@gmail.com", alias=None, biller_norm="acme_water")
    assert r.label == "SUSPICIOUS", r
    db.rollback()


def test_friend_copying_biller_you_already_pay_still_needs_confirmation(db):
    u = _user(db, "f3@example.com")
    db.add(ChargeEvent(user_id=u.id, charge_date=date.today() - timedelta(days=30), merchant_norm="acme_water",
                       amount=Decimal("649"), source="STATEMENT"))
    db.flush()
    r = _score(db, u, sender="rahul.friend@gmail.com", alias=None, biller_norm="acme_water",
               event_date=date.today())
    assert r.label != "VERIFIED_SENDER" and r.needs_confirmation, r
    db.rollback()


def test_bill_you_forwarded_to_yourself_is_not_penalised(db):
    u = _user(db, "f4@example.com", gmail="me.myself@gmail.com")
    r = _score(db, u, sender="me.myself@gmail.com", alias=None, biller_norm="acme_water")
    assert r.label == "NEW_BILLER_CONFIRM", r
    assert not any("personal" in x for x in r.reasons)
    db.rollback()


def test_real_google_play_mail_can_be_verified(db):
    u = _user(db, "f5@example.com")
    db.add(ChargeEvent(user_id=u.id, charge_date=date.today() - timedelta(days=30), merchant_norm="google_play",
                       amount=Decimal("1999"), source="RECEIPT"))
    db.flush()
    r = _score(db, u, sender="googleplay-noreply@google.com", alias=_alias(db, "google_play"),
               biller_norm="google_play", amount=Decimal("1999"), message_kind="RECEIPT", event_date=date.today())
    assert r.label == "VERIFIED_SENDER", r
    db.rollback()


def test_fake_google_play_lookalike_is_suspicious(db):
    u = _user(db, "f6@example.com")
    r = _score(db, u, sender="billing@g00gle-play.com", auth_results="dkim=fail; spf=fail; dmarc=fail",
               alias=_alias(db, "google_play"), biller_norm="google_play", amount=Decimal("1999"))
    assert r.label == "SUSPICIOUS", r
    db.rollback()


def test_future_dated_receipt_is_a_renewal():
    today = date(2026, 9, 29)
    assert effective_kind("RECEIPT", date(2026, 10, 29), today) == "RENEWAL_NOTICE"
    assert effective_kind("PAYMENT_CONFIRMATION", date(2026, 10, 29), today) == "RENEWAL_NOTICE"
    assert effective_kind("RECEIPT", date(2026, 9, 21), today) == "RECEIPT"
    assert effective_kind("DUE_NOTICE", date(2026, 10, 29), today) == "DUE_NOTICE"
