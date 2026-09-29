"""Monthly report, documents vault, bill splits, Ask Lifeline, photo-text ingest, web push."""
from __future__ import annotations

import calendar
import re
from datetime import date, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import current_user
from app.errors import ApiError
from app.models import BillSplit, Document, Obligation, PushSubscription, Reminder, User
from app.services import ask_service, pipeline, push_service, risk_service
from app.services.dedup_service import fingerprint
from app.timeutil import now_utc, today_local

router = APIRouter(tags=["features"])
E164 = re.compile(r"^\+[1-9]\d{6,14}$")


def _own_obl(db: Session, oid: str, user: User) -> Obligation:
    o = db.get(Obligation, oid)
    if o is None or o.user_id != user.id:
        raise ApiError(404, "Not found")
    return o


# --- Monthly report ------------------------------------------------------------------------
@router.get("/report")
def monthly_report(month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"), user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    today = today_local()
    y, m = (int(month[:4]), int(month[5:])) if month else (today.year, today.month)
    if not 1 <= m <= 12 or not 2000 <= y <= 2100:
        raise ApiError(422, "Month must look like 2026-09")
    start, end = date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
    obls = list(db.scalars(select(Obligation).where(Obligation.user_id == user.id)))
    paid = [o for o in obls if o.status == "PAID" and o.paid_at and start <= o.paid_at.astimezone(timezone.utc).date() <= end]
    on_time = [o for o in paid if o.paid_at.date() <= o.due_date]
    avoided = sum((risk_service.direct_cost(o.type, o.amount).amount or Decimal(0) for o in on_time), Decimal(0))
    auto = [o for o in paid if o.paid_via == "AUTO_DETECTED"]
    nm = date(y + (m == 12), m % 12 + 1, 1)
    upcoming = [o for o in obls if o.status in ("OPEN", "OVERDUE") and nm <= o.due_date <= date(nm.year, nm.month, calendar.monthrange(nm.year, nm.month)[1])]
    overdue = [o for o in obls if o.status in ("OPEN", "OVERDUE") and o.due_date < today]
    subs = [o for o in obls if o.is_recurring and o.status in ("OPEN", "OVERDUE")]
    rem = list(db.scalars(select(Reminder).where(Reminder.user_id == user.id, Reminder.simulated.is_(False))))
    rem = [r for r in rem if start <= r.scheduled_for.astimezone(timezone.utc).date() <= end]
    return {
        "month": f"{y}-{m:02d}", "label": start.strftime("%B %Y"),
        "paid_count": len(paid), "paid_total": str(sum((o.amount or 0 for o in paid), Decimal(0))),
        "paid_on_time": len(on_time), "penalties_avoided": str(avoided),
        "auto_detected": len(auto), "reminders_sent": len([r for r in rem if r.status in ("SENT", "SIMULATED")]),
        "overdue_now": [{"biller": o.biller_raw, "amount": str(o.amount) if o.amount else None, "due_date": o.due_date.isoformat()} for o in overdue],
        "next_month": {"label": nm.strftime("%B %Y"), "count": len(upcoming),
                       "total": str(sum((o.amount or 0 for o in upcoming), Decimal(0)))},
        "subscriptions": {"count": len(subs), "monthly": str(sum((o.amount * Decimal(30) / Decimal(o.recurrence_interval_days or 30)
                                                                  for o in subs if o.amount), Decimal(0)).quantize(Decimal("1")))},
        "note": "Penalties avoided = the late fee or lapse cost of each bill you paid on time (estimated).",
    }


# --- Documents vault ---------------------------------------------------------------------------
DOC_TYPES = {"PUC": "PUC", "INSURANCE_VEHICLE": "INSURANCE_VEHICLE", "DRIVING_LICENCE": "DRIVING_LICENCE",
             "VEHICLE_RC": "VEHICLE_OTHER", "PASSPORT": "DOCUMENT_OTHER", "INSURANCE_OTHER": "INSURANCE_OTHER", "OTHER": "DOCUMENT_OTHER"}


class DocIn(BaseModel):
    kind: Literal["PUC", "INSURANCE_VEHICLE", "DRIVING_LICENCE", "VEHICLE_RC", "PASSPORT", "INSURANCE_OTHER", "OTHER"]
    label: str = Field(min_length=1, max_length=120)
    number: str | None = Field(None, max_length=40)  # only the last 4 characters are kept
    vehicle_ref: str | None = Field(None, max_length=40)
    expiry_date: date


def _doc(d: Document, o: Obligation | None) -> dict:
    return {"id": d.id, "kind": d.kind, "label": d.label, "number_last4": d.number_last4, "vehicle_ref": d.vehicle_ref,
            "expiry_date": d.expiry_date.isoformat(), "obligation_id": d.obligation_id,
            "days_left": (d.expiry_date - today_local()).days, "status": o.status if o else None}


@router.get("/documents")
def list_docs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    docs = list(db.scalars(select(Document).where(Document.user_id == user.id).order_by(Document.expiry_date)))
    return [_doc(d, db.get(Obligation, d.obligation_id) if d.obligation_id else None) for d in docs]


@router.post("/documents", status_code=201)
def add_doc(body: DocIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    last4 = re.sub(r"[^A-Za-z0-9]", "", body.number or "")[-4:] or None
    veh = re.sub(r"[\s-]", "", body.vehicle_ref or "").upper() or None
    otype = DOC_TYPES[body.kind]
    o = Obligation(user_id=user.id, origin="DEMO" if user.is_demo else "REAL", type=otype, biller_raw=body.label.strip(),
                   biller_norm=re.sub(r"[^a-z0-9]+", "_", body.label.lower()).strip("_"), due_date=body.expiry_date,
                   status="OVERDUE" if body.expiry_date < today_local() else "OPEN", source_kinds=["DOCUMENT"],
                   trust_label="NOT_APPLICABLE", confidence=1.0, extractors_agreed=True, message_kind="RENEWAL_NOTICE",
                   vehicle_ref=veh, fingerprint="")
    o.fingerprint = fingerprint(o.biller_norm, otype, None, body.expiry_date, veh)
    db.add(o)
    db.flush()
    d = Document(user_id=user.id, kind=body.kind, label=body.label.strip(), number_last4=last4, vehicle_ref=veh,
                 expiry_date=body.expiry_date, obligation_id=o.id)
    db.add(d)
    db.commit()
    return _doc(d, o)


@router.delete("/documents/{did}")
def delete_doc(did: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = db.get(Document, did)
    if d is None or d.user_id != user.id:
        raise ApiError(404, "Not found")
    o = db.get(Obligation, d.obligation_id) if d.obligation_id else None
    if o is not None and o.status in ("OPEN", "OVERDUE"):
        o.status = "DISMISSED"
    db.delete(d)
    db.commit()
    return {"status": "removed"}


# --- Bill splits ---------------------------------------------------------------------------
class SplitPerson(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone_e164: str | None = None

    @field_validator("phone_e164")
    @classmethod
    def _p(cls, v):
        if v in (None, ""):
            return None
        v = v.replace(" ", "")
        if not E164.match(v):
            raise ValueError("phone must be E.164, e.g. +919876543210")
        return v


class SplitIn(BaseModel):
    people: list[SplitPerson] = Field(min_length=1, max_length=10)
    include_me: bool = True


def _splits(db: Session, o: Obligation) -> dict:
    rows = list(db.scalars(select(BillSplit).where(BillSplit.obligation_id == o.id)))
    owed = sum((r.share_amount for r in rows if not r.paid), Decimal(0))
    return {"obligation_id": o.id, "amount": str(o.amount) if o.amount is not None else None,
            "shares": [{"id": r.id, "name": r.name, "phone_e164": r.phone_e164, "share_amount": str(r.share_amount),
                        "paid": r.paid, "reminded_at": r.reminded_at} for r in rows],
            "others_owe": str(owed),
            "my_share": str((o.amount or 0) - sum((r.share_amount for r in rows), Decimal(0))) if o.amount is not None else None}


@router.get("/obligations/{oid}/splits")
def get_splits(oid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _splits(db, _own_obl(db, oid, user))


@router.post("/obligations/{oid}/splits")
def set_splits(oid: str, body: SplitIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    o = _own_obl(db, oid, user)
    if o.amount is None:
        raise ApiError(422, "This bill has no amount to split.")
    for r in db.scalars(select(BillSplit).where(BillSplit.obligation_id == o.id)):
        db.delete(r)
    n = len(body.people) + (1 if body.include_me else 0)
    share = (o.amount / n).quantize(Decimal("0.01"))
    for p in body.people:
        db.add(BillSplit(obligation_id=o.id, user_id=user.id, name=p.name.strip(), phone_e164=p.phone_e164, share_amount=share))
    db.commit()
    return _splits(db, o)


@router.post("/splits/{sid}/paid")
def split_paid(sid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = db.get(BillSplit, sid)
    if r is None or r.user_id != user.id:
        raise ApiError(404, "Not found")
    r.paid = True
    db.commit()
    return _splits(db, db.get(Obligation, r.obligation_id))


@router.post("/splits/{sid}/remind")
def split_remind(sid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = db.get(BillSplit, sid)
    if r is None or r.user_id != user.id:
        raise ApiError(404, "Not found")
    o = db.get(Obligation, r.obligation_id)
    text = (f"Hi {r.name}, a reminder from {user.name or 'your flatmate'} via Lifeline: your share of "
            f"{o.biller_raw} is ₹{r.share_amount:,.2f}, due {o.due_date:%d %b}.")
    sent = False
    if get_settings().twilio_live and not user.is_demo and r.phone_e164:
        from app.services import whatsapp_service

        sent = whatsapp_service.send_whatsapp(r.phone_e164, text)
    r.reminded_at = now_utc()
    db.commit()
    return {"status": "SENT" if sent else "SIMULATED", "message": text}


# --- Ask Lifeline -----------------------------------------------------------------------------
class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=300)


@router.post("/ask")
def ask(body: AskIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return ask_service.answer(db, user, body.question)


@router.get("/ask/suggestions")
def suggestions():
    return ask_service.SUGGESTIONS


# --- Text read on the device (photo OCR in the browser) ------------------------------------------
class TextIn(BaseModel):
    text: str = Field(min_length=3, max_length=20000)


@router.post("/ingest/text")
def ingest_text(body: TextIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Text read from a bill photo on the user's own device; goes through the same pipeline."""
    res = pipeline.process_incoming(db, user, "UPLOAD", body.text, pipeline.IncomingMeta(
        origin="DEMO" if user.is_demo else "REAL", skip_new_biller_check=True))
    db.commit()
    return res.as_dict()


# --- Web push ----------------------------------------------------------------------------------
class PushSubIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=600)
    keys: dict[str, str]


@router.get("/push/vapid-public-key")
def vapid_key():
    s = get_settings()
    return {"enabled": s.push_enabled, "key": s.vapid_public_key or None}


@router.post("/push/subscribe", status_code=201)
def push_subscribe(body: PushSubIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not body.endpoint.startswith("https://"):
        raise ApiError(422, "Invalid push endpoint")
    if not body.keys.get("p256dh") or not body.keys.get("auth"):
        raise ApiError(422, "Missing push keys")
    sub = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    if sub is None:
        sub = PushSubscription(user_id=user.id, endpoint=body.endpoint, p256dh=body.keys["p256dh"], auth=body.keys["auth"])
        db.add(sub)
    else:
        sub.user_id, sub.p256dh, sub.auth = user.id, body.keys["p256dh"], body.keys["auth"]
    db.commit()
    return {"status": "subscribed"}


@router.post("/push/test")
def push_test(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not push_service.enabled():
        raise ApiError(409, "Push isn't configured on this server (VAPID keys missing).")
    n = push_service.send(db, user, "Lifeline", "Notifications are on. You'll hear from us before anything costly slips.", "/reminders")
    db.commit()
    if n == 0:
        raise ApiError(409, "No browser is subscribed yet — press Enable notifications first.")
    return {"delivered": n}


@router.get("/push/status")
def push_status(user: User = Depends(current_user), db: Session = Depends(get_db)):
    n = len(list(db.scalars(select(PushSubscription).where(PushSubscription.user_id == user.id))))
    return {"enabled": push_service.enabled(), "subscriptions": n}

