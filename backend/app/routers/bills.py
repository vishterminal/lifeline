"""Output side, first slice: ₹-risk ranking, obligation chain, what-if, and bill actions
(mock pay / mark paid / dismiss / snooze). Payments are always simulated."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.errors import ApiError
from app.models import Obligation, Payment, User
from app.schemas import ObligationOut
from app.services import reminder_service, risk_service, shock_service
from app.timeutil import now_utc, today_local

router = APIRouter(tags=["bills"])


def _all(db: Session, user: User) -> list[Obligation]:
    return list(db.scalars(select(Obligation).where(Obligation.user_id == user.id)))


def _own(db: Session, oid: str, user: User) -> Obligation:
    o = db.get(Obligation, oid)
    if o is None or o.user_id != user.id:
        raise ApiError(404, "Not found")
    return o


def _with_risk(o: Obligation, everything: list[Obligation]) -> dict:
    c = risk_service.assess(o, everything, today_local())
    return {**ObligationOut.model_validate(o).model_dump(mode="json"), "consequence": c.as_dict(), "chain_hint": c.chain_hint,
            "shock": shock_service.bill_shock(o, everything) if o.status in risk_service.OPEN else None}


@router.get("/bills")
def ranked_bills(sort: str = Query("risk", pattern="^(risk|date)$"), user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    """All bills with ₹ consequence. Default order: open first, then ₹ risk desc, then due date asc."""
    everything = _all(db, user)
    rows = [_with_risk(o, everything) for o in everything]
    is_open = lambda r: r["status"] in risk_service.OPEN  # noqa: E731
    if sort == "risk":
        rows.sort(key=lambda r: (not is_open(r), -Decimal(r["consequence"]["total"]), r["due_date"]))
    else:
        rows.sort(key=lambda r: (not is_open(r), r["due_date"]))
    return rows


@router.get("/obligations/{oid}/chain")
def chain(oid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = risk_service.assess(_own(db, oid, user), _all(db, user), today_local()).as_dict()
    return {"upstream": c["upstream"], "downstream": c["downstream_links"], "explanations": c["explanation"],
            "chain_hint": c["chain_hint"]}


@router.get("/obligations/{oid}/whatif")
def whatif(oid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return risk_service.what_if(_own(db, oid, user), _all(db, user), today_local())


def _close(o: Obligation, status: str, via: str | None, db: Session | None = None) -> None:
    if o.status not in risk_service.OPEN:
        raise ApiError(409, f"This bill is already {o.status.lower()}")
    o.status = status
    if db is not None:  # everything stops the moment a bill is paid or dismissed
        reminder_service.acknowledge(db, o, "PAID" if status == "PAID" else "DISMISS")
    if status == "PAID":
        o.paid_via, o.paid_at = via, now_utc()


@router.post("/obligations/{oid}/pay-mock")
def pay_mock(oid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Simulated payment: never uses links from the original message, no real money moves."""
    o = _own(db, oid, user)
    _close(o, "PAID", "MOCK", db)
    p = Payment(obligation_id=o.id, user_id=user.id, amount=o.amount, is_mock=True)
    db.add(p)
    db.commit()
    return {"payment": {"id": p.id, "amount": str(p.amount) if p.amount is not None else None, "is_mock": True,
                        "note": "Simulated — no real money moved"},
            "obligation": ObligationOut.model_validate(o)}


@router.post("/obligations/{oid}/mark-paid", response_model=ObligationOut)
def mark_paid(oid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    o = _own(db, oid, user)
    _close(o, "PAID", "USER_MARKED", db)
    db.commit()
    return o


@router.post("/obligations/{oid}/dismiss", response_model=ObligationOut)
def dismiss(oid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    o = _own(db, oid, user)
    _close(o, "DISMISSED", None, db)
    db.commit()
    return o


class SnoozeIn(BaseModel):
    minutes: int = Field(ge=1, le=1440)


@router.post("/obligations/{oid}/snooze", response_model=ObligationOut)
def snooze(oid: str, body: SnoozeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    o = _own(db, oid, user)
    o.snoozed_until = now_utc() + timedelta(minutes=body.minutes)
    reminder_service.acknowledge(db, o, "SNOOZE_30" if body.minutes >= 30 else "SNOOZE_15")
    db.commit()
    return o
