"""R-RECURRING and R-PAID-DETECT (spec F11, F14, Section 13)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ChargeEvent, Obligation
from app.services.dedup_service import OPEN_STATES, fingerprint

AMOUNT_TOL = Decimal("0.05")
PAID_TOL = Decimal("0.02")


def detect_pattern(charges: list[ChargeEvent]) -> int | None:
    """Return interval days (30 or 365) if the latest charges form a recurring pattern."""
    if len(charges) < 2:
        return None
    charges = sorted(charges, key=lambda c: c.charge_date)
    latest = charges[-1].amount
    similar = [c for c in charges if abs(c.amount - latest) <= latest * AMOUNT_TOL]
    # Price changes are allowed on the newest charge; compare earlier ones against each other too.
    series = similar if len(similar) >= 2 else charges
    gaps = [(b.charge_date - a.charge_date).days for a, b in zip(series, series[1:])]
    if gaps and all(25 <= g <= 35 for g in gaps):
        return 30
    if gaps and all(355 <= g <= 375 for g in gaps):
        return 365
    return None


def find_subscription(db: Session, user_id: str, merchant_norm: str) -> Obligation | None:
    return db.scalar(select(Obligation).where(
        Obligation.user_id == user_id, Obligation.biller_norm == merchant_norm,
        Obligation.is_recurring.is_(True), Obligation.status.in_(OPEN_STATES),
    ).order_by(Obligation.due_date.desc()))


def update_recurring(db: Session, user_id: str, merchant_norm: str, display: str | None,
                     otype: str = "SUBSCRIPTION", origin: str = "REAL", source_kind: str = "STATEMENT") -> Obligation | None:
    """After a new charge: create/update the recurring obligation when a pattern exists."""
    charges = list(db.scalars(select(ChargeEvent).where(
        ChargeEvent.user_id == user_id, ChargeEvent.merchant_norm == merchant_norm)))
    sub = find_subscription(db, user_id, merchant_norm)
    interval = detect_pattern(charges) or (sub.recurrence_interval_days if sub else None)
    if not interval:
        return None
    charges.sort(key=lambda c: c.charge_date)
    last = charges[-1]
    prev = charges[-2] if len(charges) >= 2 else None
    next_date = last.charge_date + timedelta(days=interval)
    price_changed = bool(prev and abs(last.amount - prev.amount) > prev.amount * AMOUNT_TOL)
    if sub is None:
        sub = Obligation(user_id=user_id, origin=origin, type=otype, biller_raw=display or merchant_norm,
                         biller_norm=merchant_norm, source_kinds=[source_kind], trust_label="NOT_APPLICABLE",
                         confidence=0.9, extractors_agreed=True, message_kind="RECEIPT")
        db.add(sub)
    elif source_kind not in (sub.source_kinds or []):
        sub.source_kinds = [*(sub.source_kinds or []), source_kind]
    if sub.due_date is None or next_date > sub.due_date or sub.status != "OPEN":
        sub.due_date = next_date
    sub.status = "OPEN"
    sub.amount = last.amount
    sub.is_recurring = True
    sub.recurrence_interval_days = interval
    sub.next_expected_date = next_date
    sub.price_changed = price_changed
    sub.fingerprint = fingerprint(sub.biller_norm, sub.type, sub.amount, sub.due_date, sub.vehicle_ref)
    db.flush()
    return sub


def detect_paid(db: Session, user_id: str, biller_norm: str | None, amount: Decimal | None,
                event_date: date | None) -> Obligation | None:
    """A payment confirmation / receipt that matches an open obligation marks it PAID."""
    if not biller_norm or amount is None:
        return None
    cands = list(db.scalars(select(Obligation).where(
        Obligation.user_id == user_id, Obligation.biller_norm == biller_norm,
        Obligation.status.in_(OPEN_STATES), Obligation.amount.is_not(None),
    ).order_by(Obligation.due_date)))
    for o in cands:
        if abs(o.amount - amount) <= o.amount * PAID_TOL:
            if event_date and o.is_recurring and (o.due_date - event_date).days > 10:
                continue  # a charge long before the next renewal is the previous cycle
            o.status = "PAID"
            o.paid_via = "AUTO_DETECTED"
            o.paid_at = datetime.now(timezone.utc)
            db.flush()
            return o
    return None
