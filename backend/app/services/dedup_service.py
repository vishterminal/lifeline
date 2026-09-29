"""R-DEDUP: fingerprint + ±3-day merge (spec F10)."""
from __future__ import annotations

import hashlib
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Obligation

OPEN_STATES = ("OPEN", "OVERDUE")


def fingerprint(biller_norm: str | None, otype: str, amount: Decimal | None, due_date, vehicle_ref: str | None) -> str:
    amt = f"{amount:.2f}" if amount is not None else ""
    raw = f"{biller_norm or ''}|{otype}|{amt}|{due_date.isoformat() if due_date else ''}|{vehicle_ref or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()


def find_match(db: Session, user_id: str, fp: str, biller_norm: str | None, otype: str, due_date) -> Obligation | None:
    q = select(Obligation).where(Obligation.user_id == user_id, Obligation.status.in_(OPEN_STATES))
    exact = db.scalar(q.where(Obligation.fingerprint == fp))
    if exact:
        return exact
    if not biller_norm or due_date is None:
        return None
    return db.scalar(q.where(
        Obligation.biller_norm == biller_norm,
        Obligation.type == otype,
        Obligation.due_date >= due_date - timedelta(days=3),
        Obligation.due_date <= due_date + timedelta(days=3),
    ))


def merge_into(existing: Obligation, source_kind: str, fields: dict, confidence: float) -> None:
    kinds = list(existing.source_kinds or [])
    if source_kind not in kinds:
        kinds.append(source_kind)
    existing.source_kinds = kinds
    if confidence > (existing.confidence or 0):
        for k in ("amount", "due_date", "biller_raw", "vehicle_ref"):
            if fields.get(k) is not None:
                setattr(existing, k, fields[k])
        existing.confidence = confidence
        existing.extractors_agreed = fields.get("extractors_agreed", existing.extractors_agreed)
    existing.fingerprint = fingerprint(existing.biller_norm, existing.type, existing.amount,
                                       existing.due_date, existing.vehicle_ref)
