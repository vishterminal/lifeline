"""Penalty Fighter (F18), cash-flow planner (F14), life-load score (F21),
subscriptions + savings (F11/F19) and delete-all-my-data (F22)."""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.errors import ApiError
from app.models import BillerAlias, ChargeEvent, Obligation, User, WaiverDraft
from app.services import risk_service
from app.timeutil import now_utc, today_local

router = APIRouter(tags=["insights"])
OPEN = ("OPEN", "OVERDUE")


def _all(db: Session, user: User) -> list[Obligation]:
    return list(db.scalars(select(Obligation).where(Obligation.user_id == user.id)))


def _own(db: Session, oid: str, user: User) -> Obligation:
    o = db.get(Obligation, oid)
    if o is None or o.user_id != user.id:
        raise ApiError(404, "Not found")
    return o


def _inr(v) -> str:
    return "[amount]" if v is None else f"Rs. {Decimal(v):,.2f}"


# --- Penalty Fighter ----------------------------------------------------------------------
def draft_waiver(o: Obligation, user: User, on_time: int, late_fee: Decimal | None, today: date) -> str:
    """Facts only: no invented account numbers, dates or policies; [placeholders] for unknowns."""
    days_late = max(0, (today - o.due_date).days)
    biller = o.biller_raw or o.biller_norm or "[biller]"
    lines = [
        f"Subject: Request to waive the late fee on my {biller} bill",
        "",
        f"Dear {biller} Customer Care,",
        "",
        f"I am writing about my bill of {_inr(o.amount)} that was due on {o.due_date:%d %B %Y}. "
        + (f"I am {days_late} day(s) late with this payment. " if days_late else "")
        + "The delay was unintentional and I have [paid / will pay] the full amount on [date].",
    ]
    if on_time:
        lines.append(f"I have paid my previous {on_time} bill(s) with you on time and value the service.")
    lines += [
        (f"I kindly request a one-time waiver of the late fee ({_inr(late_fee)}). " if late_fee else
         "I kindly request a one-time waiver of any late fee or penalty on this bill. ")
        + "I will make sure future payments are made before the due date.",
        "",
        "Account / consumer number: [your account number]",
        "",
        "Thank you for your consideration.",
        f"{user.name or '[your name]'}",
        "[phone number]",
    ]
    return "\n".join(lines)


@router.post("/obligations/{oid}/waiver-draft")
def waiver_draft(oid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    o = _own(db, oid, user)
    today = today_local()
    late = o.status == "OVERDUE" or (o.status == "OPEN" and o.due_date < today) or \
        (o.status == "PAID" and o.paid_at and o.paid_at.date() > o.due_date)
    if not late:
        raise ApiError(409, "Penalty Fighter is for bills that are overdue or were paid late.")
    everything = _all(db, user)
    on_time = sum(1 for x in everything if x.biller_norm == o.biller_norm and x.id != o.id and x.status == "PAID")
    fee = risk_service.direct_cost(o.type, o.amount).amount
    text = draft_waiver(o, user, on_time, fee, today)
    d = WaiverDraft(obligation_id=o.id, user_id=user.id, biller_norm=o.biller_norm, draft_text=text)
    db.add(d)
    db.commit()
    outcomes = [w.outcome for w in db.scalars(select(WaiverDraft).where(
        WaiverDraft.biller_norm == o.biller_norm, WaiverDraft.outcome != "UNKNOWN"))]
    likelihood = (f"{sum(x == 'GRANTED' for x in outcomes) * 100 // len(outcomes)}% granted "
                  f"({len(outcomes)} recorded outcomes)") if len(outcomes) >= 5 else \
        "Unknown — not enough recorded outcomes yet (needs 5+ for this biller)"
    return {"draft_id": d.id, "text": text, "likelihood": likelihood, "facts_used": {
        "biller": o.biller_raw, "amount": str(o.amount) if o.amount is not None else None,
        "due_date": o.due_date.isoformat(), "days_late": max(0, (today - o.due_date).days), "on_time_history": on_time}}


class OutcomeIn(BaseModel):
    outcome: Literal["GRANTED", "DENIED", "UNKNOWN"]


@router.patch("/waiver-drafts/{did}")
def waiver_outcome(did: str, body: OutcomeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = db.get(WaiverDraft, did)
    if d is None or d.user_id != user.id:
        raise ApiError(404, "Not found")
    d.outcome, d.outcome_at = body.outcome, now_utc()
    db.commit()
    return {"id": d.id, "outcome": d.outcome}


# --- Cash-flow planner -----------------------------------------------------------------------
def _salary_dates(day_of_month: int, start: date, end: date) -> list[date]:
    out, y, m = [], start.year, start.month
    while True:
        d = date(y, m, min(day_of_month, calendar.monthrange(y, m)[1]))  # salary day 31 in a 30-day month
        if d > end:
            return out
        if d >= start:
            out.append(d)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


@router.get("/cashflow/plan")
def cashflow(days: int = Query(45, ge=7, le=120), user: User = Depends(current_user), db: Session = Depends(get_db)):
    today = today_local()
    end = today + timedelta(days=days)
    everything = _all(db, user)
    bills = sorted([o for o in everything if o.status in OPEN and o.amount is not None and o.due_date <= end],
                   key=lambda o: o.due_date)
    assumptions = ["Balance is a snapshot you entered, not live bank data."]
    if user.balance_amount is None:
        return {"needs_balance": True, "schedule": [], "balance_line": [], "warnings": [],
                "assumptions": ["Add your current balance in Settings to plan payments."]}
    salaries = _salary_dates(user.salary_day, today, end) if user.salary_day else []
    if user.salary_day and user.salary_amount is None:
        assumptions.append("Salary amount unknown — salary days are shown but not added to the balance.")
    if not user.salary_day:
        assumptions.append("No salary day set — planning against your current balance only.")
    income = Decimal(user.salary_amount or 0)

    risk = {o.id: risk_service.assess(o, everything, today) for o in bills}
    balance = Decimal(user.balance_amount)
    schedule, warnings, line = [], [], []
    by_day = defaultdict(list)
    for o in bills:
        by_day[max(o.due_date, today)].append(o)
    short = []
    d = today
    while d <= end:
        if d in salaries and income:
            balance += income
        for o in sorted(by_day.get(d, []), key=lambda x: -(risk[x.id].total / max(x.amount, 1))):
            if balance >= o.amount:
                balance -= o.amount
                schedule.append({"obligation_id": o.id, "biller": o.biller_raw, "amount": str(o.amount),
                                 "due_date": o.due_date.isoformat(), "pay_on": d.isoformat(), "status": "PLANNED",
                                 "risk": str(risk[o.id].total)})
            else:
                short.append(o)
                next_salary = next((s for s in salaries if s > d), None)
                schedule.append({"obligation_id": o.id, "biller": o.biller_raw, "amount": str(o.amount),
                                 "due_date": o.due_date.isoformat(), "pay_on": None, "status": "SHORT",
                                 "risk": str(risk[o.id].total)})
                msg = f"Short by ₹{o.amount - balance:,.0f} for {o.biller_raw} due {o.due_date:%d %b}."
                if next_salary:
                    msg += f" Salary arrives after this due date ({next_salary:%d %b})."
                warnings.append(msg)
        line.append({"date": d.isoformat(), "balance": str(balance), "salary": d in salaries})
        d += timedelta(days=1)
    if short:
        # Advise across every bill competing for the same money (due up to the last shortfall),
        # not just the ones that couldn't be covered.
        last_short = max(o.due_date for o in short)
        competing = [o for o in bills if o.due_date <= last_short]
        top = max(competing, key=lambda o: risk[o.id].total / max(o.amount, 1))
        warnings.insert(0, f"Money is tight: pay {top.biller_raw} first — it has the highest penalty per rupee. "
                           f"{len(short)} bill(s) can't be covered before salary.")
    return {"needs_balance": False, "schedule": schedule, "balance_line": line, "warnings": warnings,
            "assumptions": assumptions, "salary_days": [s.isoformat() for s in salaries],
            "start_balance": str(user.balance_amount), "end_balance": str(balance)}


# --- Life-load score -------------------------------------------------------------------------
@router.get("/lifeload")
def lifeload(user: User = Depends(current_user), db: Session = Depends(get_db)):
    today = today_local()
    everything = _all(db, user)
    soon = [o for o in everything if o.status in OPEN and (o.due_date - today).days <= 7]
    weight = {"HIGH": 5, "MEDIUM": 2, "LOW": 1}
    pts = sum(weight[risk_service.assess(o, everything, today).tier] for o in soon)
    score = min(100, pts * 8)
    label = "Light" if score < 30 else "Moderate" if score < 60 else "Heavy"
    return {"score": score, "label": label, "items_next_7_days": len(soon)}


# --- Subscriptions + savings -----------------------------------------------------------------
@router.get("/subscriptions")
def subscriptions(user: User = Depends(current_user), db: Session = Depends(get_db)):
    today = today_local()
    aliases = {a.canonical_name: a for a in db.scalars(select(BillerAlias))}
    subs = [o for o in _all(db, user) if o.is_recurring and o.status in OPEN]
    year_ago = today - timedelta(days=365)
    charges = list(db.scalars(select(ChargeEvent).where(ChargeEvent.user_id == user.id, ChargeEvent.charge_date >= year_ago)))
    rows = []
    for o in subs:
        a = aliases.get(o.biller_norm or "")
        paid = sum((c.amount for c in charges if c.merchant_norm == o.biller_norm), Decimal(0))
        monthly = o.amount * Decimal(30) / Decimal(o.recurrence_interval_days or 30) if o.amount else None
        rows.append({"obligation_id": o.id, "biller": o.biller_raw, "amount": str(o.amount) if o.amount else None,
                     "next_renewal": (o.next_expected_date or o.due_date).isoformat(),
                     "interval_days": o.recurrence_interval_days, "price_changed": o.price_changed,
                     "monthly_cost": str(monthly.quantize(Decimal("1"))) if monthly else None,
                     "paid_last_12_months": str(paid), "category": a.category if a else None,
                     "autopay": o.autopay, "usage": o.usage,
                     "manage_url": a.official_account_url if a else None})
    by_cat = defaultdict(list)
    for r in rows:
        if r["category"]:
            by_cat[r["category"]].append(r["biller"])
    duplicates = [{"category": k.replace("_", " ").title(), "services": v} for k, v in by_cat.items() if len(v) > 1]
    monthly_total = sum((Decimal(r["monthly_cost"]) for r in rows if r["monthly_cost"]), Decimal(0))
    unused = sum((Decimal(r["monthly_cost"]) for r in rows if r["usage"] == "NOT_USING" and r["monthly_cost"]), Decimal(0))
    return {"subscriptions": rows, "duplicates": duplicates, "monthly_total": str(monthly_total),
            "potential_savings_yearly": str(unused * 12),
            "autopay_count": sum(1 for r in rows if r["autopay"]),
            "yearly_total": str(monthly_total * 12),
            "note": "Usage-based suggestions (e.g. 'unused for 40 days') need data Lifeline doesn't have."}


class UsageIn(BaseModel):
    using: bool


@router.post("/subscriptions/{oid}/usage")
def set_usage(oid: str, body: UsageIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The user's answer to "Still using it?" (Lifeline can't see usage; it asks)."""
    o = _own(db, oid, user)
    if not o.is_recurring:
        raise ApiError(409, "Only subscriptions can be marked as used or not used.")
    o.usage = "USING" if body.using else "NOT_USING"
    db.commit()
    return {"obligation_id": o.id, "usage": o.usage}


# --- Delete all my data ---------------------------------------------------------------------
class DeleteIn(BaseModel):
    confirm: str


@router.delete("/me/data")
def delete_everything(body: DeleteIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.confirm.strip().upper() != "DELETE":
        raise ApiError(422, 'Type DELETE to confirm.')
    from app.services import gmail_service

    try:
        gmail_service.disconnect(db, user)  # revokes + deletes the Gmail token
    except Exception:
        pass
    db.delete(user)  # every user-owned row cascades
    db.commit()
    return {"status": "deleted"}
