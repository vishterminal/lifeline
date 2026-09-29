"""Reminders feed, run-now tick, fast-forward simulation, and family contacts."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.errors import ApiError
from app.models import FamilyContact, Obligation, Reminder, User
from app.services import reminder_service
from app.timeutil import now_utc

router = APIRouter(tags=["reminders"])


@router.get("/reminders")
def list_reminders(limit: int = Query(100, ge=1, le=500), user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Reminder, Obligation).join(Obligation, Obligation.id == Reminder.obligation_id)
                      .where(Reminder.user_id == user.id).order_by(Reminder.scheduled_for.desc()).limit(limit)).all()
    return [{
        "id": r.id, "obligation_id": o.id, "biller": o.biller_raw or o.biller_norm,
        "amount": str(o.amount) if o.amount is not None else None, "obligation_status": o.status,
        "channel": r.channel, "tier": r.tier, "stage": r.stage, "attempt_no": r.attempt_no,
        "scheduled_for": r.scheduled_for, "status": r.status, "message": r.message, "simulated": r.simulated,
        "ack_type": r.ack_type, "error": r.error,
    } for r, o in rows]


@router.post("/reminders/tick")
def run_tick(user: User = Depends(current_user), db: Session = Depends(get_db)):
    res = reminder_service.tick(db, user)
    db.commit()
    return res.as_dict()


class SimIn(BaseModel):
    days: int = Field(7, ge=1, le=30)


@router.post("/reminders/simulate")
def simulate(body: SimIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    days = reminder_service.simulate_days(db, user, body.days)
    db.commit()
    return {"days": days, "total": {k: sum(d[k] for d in days) for k in ("sent", "simulated", "skipped", "family")}}


@router.delete("/reminders/simulated")
def clear_simulated(user: User = Depends(current_user), db: Session = Depends(get_db)):
    n = db.execute(delete(Reminder).where(Reminder.user_id == user.id, Reminder.simulated.is_(True))).rowcount
    db.commit()
    return {"removed": n}


# --- Family contacts ---------------------------------------------------------------------
class FamilyIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone_e164: str
    consented: bool = False

    @field_validator("phone_e164")
    @classmethod
    def _e164(cls, v: str) -> str:
        v = v.replace(" ", "")
        if not re.fullmatch(r"\+[1-9]\d{6,14}", v):
            raise ValueError("phone must be E.164, e.g. +919876543210")
        return v


def _fc(f: FamilyContact) -> dict:
    return {"id": f.id, "name": f.name, "phone_e164": f.phone_e164, "consented": f.consented, "consented_at": f.consented_at}


@router.get("/family")
def list_family(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [_fc(f) for f in db.scalars(select(FamilyContact).where(FamilyContact.user_id == user.id))]


@router.post("/family", status_code=201)
def add_family(body: FamilyIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not body.consented:
        raise ApiError(422, "They must agree to receive alerts - tick the consent box.")
    f = FamilyContact(user_id=user.id, name=body.name.strip(), phone_e164=body.phone_e164, consented=True,
                      consented_at=now_utc())
    db.add(f)
    db.commit()
    return _fc(f)


@router.delete("/family/{fid}")
def remove_family(fid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = db.get(FamilyContact, fid)
    if f is None or f.user_id != user.id:
        raise ApiError(404, "Not found")
    db.delete(f)
    db.commit()
    return {"status": "removed"}
