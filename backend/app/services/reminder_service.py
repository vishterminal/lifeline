"""Reminder & escalation engine (spec F16, R-ESCALATE).

Loudness follows ₹ risk: the tier from risk_service decides which days and which
channels. A reminder is recorded per (obligation, stage, channel, attempt), so a tick
is idempotent. Everything stops the moment a bill is paid or dismissed.

Channels: IN_APP always; PUSH and WHATSAPP are really sent only when the connector
is live, otherwise recorded as SIMULATED (demo). FAMILY_WHATSAPP only for a consenting
family contact, HIGH risk, due within 24 h, after the repeat cap is used up.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import FamilyContact, Obligation, Reminder, User
from app.services import risk_service
from app.timeutil import tz

log = logging.getLogger("lifeline.reminders")

OPEN = ("OPEN", "OVERDUE")
REPEAT_EVERY = timedelta(hours=3)
# tier -> {days-before-due: channels}
LADDER: dict[str, dict[int, tuple[str, ...]]] = {
    "LOW": {7: ("IN_APP", "PUSH"), 1: ("IN_APP", "PUSH")},
    "MEDIUM": {3: ("IN_APP", "PUSH"), 1: ("IN_APP", "PUSH", "WHATSAPP")},
    "HIGH": {7: ("IN_APP", "PUSH"), 3: ("IN_APP", "PUSH", "WHATSAPP"), 1: ("IN_APP", "PUSH", "WHATSAPP"),
             0: ("IN_APP", "PUSH", "WHATSAPP")},
}
REPEAT_STAGES = {"MEDIUM": {1}, "HIGH": {1, 0}}  # repeat every 3 h until acknowledged (capped)


@dataclass
class TickResult:
    sent: int = 0
    simulated: int = 0
    skipped: int = 0
    family: int = 0

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _aware(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def in_quiet_hours(user: User, now: datetime) -> bool:
    local = now.astimezone(tz()).time()
    start, end = user.quiet_start or time(21, 0), user.quiet_end or time(8, 0)
    return (local >= start or local < end) if start > end else (start <= local < end)


def _money(v) -> str:
    return "amount unknown" if v is None else f"₹{Decimal(v):,.0f}"


def message_for(o: Obligation, c: risk_service.Consequence, days_left: int) -> str:
    when = "today" if days_left == 0 else "tomorrow" if days_left == 1 else \
        f"{-days_left} day(s) ago" if days_left < 0 else f"in {days_left} days"
    head = f"{o.biller_raw or o.biller_norm} {_money(o.amount)} {'was due' if days_left < 0 else 'due'} {when}."
    risk = f" {_money(c.total)} at risk if missed ({c.label.lower()})." if c.total else ""
    chain = f" {c.chain_hint}." if c.chain_hint else ""
    return (head + risk + chain + " Reply PAID after paying, or 15 / 30 to be reminded later.")[:400]


def _whatsapp_window_open(user: User, now: datetime) -> bool:
    last = _aware(user.whatsapp_last_inbound_at)
    return bool(last and now - last < timedelta(hours=24))


def _deliver(db: Session, user: User, o: Obligation, channel: str, tier: str, stage: str, attempt: int,
             now: datetime, text: str, simulated: bool, res: TickResult) -> str:
    s = get_settings()
    live_wa = s.twilio_live and not user.is_demo
    status, error = "SIMULATED", None
    if channel == "IN_APP":
        status = "SENT"
    elif channel == "WHATSAPP":
        if live_wa and not simulated:
            if not user.phone_e164 or not _whatsapp_window_open(user, now):
                status, error = "SKIPPED_WINDOW_CLOSED", "No message from you in 24 h - sent as push instead"
            else:
                from app.services import whatsapp_service

                ok = whatsapp_service.send_whatsapp(user.phone_e164, text)
                status = "SENT" if ok else "FAILED"
    elif channel == "PUSH" and not simulated:
        from app.services import push_service

        if push_service.enabled() and push_service.send(db, user, "Lifeline reminder", text, "/reminders"):
            status = "SENT"
    elif channel == "FAMILY_WHATSAPP":
        status = "SIMULATED" if (simulated or not live_wa) else "SENT"
    db.add(Reminder(obligation_id=o.id, user_id=user.id, channel=channel, tier=tier, stage=stage,
                    attempt_no=attempt, scheduled_for=now, status=status, message=text, simulated=simulated,
                    error=error))
    if status == "SENT":
        res.sent += 1
    elif status == "SIMULATED":
        res.simulated += 1
    else:
        res.skipped += 1
    return status


def _stage_for(tier: str, days_left: int) -> int | None:
    stages = sorted(LADDER[tier])  # e.g. [0, 1, 3, 7]
    for d in stages:
        if days_left <= d:
            return d
    return None


def tick(db: Session, user: User, now: datetime | None = None, simulated: bool = False) -> TickResult:
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(tz()).date()
    res = TickResult()
    obls = list(db.scalars(select(Obligation).where(Obligation.user_id == user.id)))
    quiet = in_quiet_hours(user, now)
    cap = max(1, user.repeat_cap or get_settings().reminder_repeat_cap)
    for o in obls:
        if o.status not in OPEN:
            continue
        if _aware(o.snoozed_until) and _aware(o.snoozed_until) > now:
            continue
        days_left = (o.due_date - today).days
        c = risk_service.assess(o, obls, today)
        tier = c.tier
        prior = list(db.scalars(select(Reminder).where(Reminder.obligation_id == o.id)))
        if days_left < 0:
            if not any(r.stage == "OVERDUE" for r in prior):  # a single overdue nudge
                _deliver(db, user, o, "IN_APP", tier, "OVERDUE", 1, now, message_for(o, c, days_left), simulated, res)
            continue
        d = _stage_for(tier, days_left)
        if d is None:
            continue
        stage = f"T-{d}"
        done = [r for r in prior if r.stage == stage and r.channel == "IN_APP"]
        if done:
            last = max(_aware(r.scheduled_for) for r in done)
            repeatable = d in REPEAT_STAGES.get(tier, set()) and len(done) < cap and now - last >= REPEAT_EVERY
            if not repeatable:
                # Family alert: HIGH, due within 24 h, cap used up, still not acknowledged.
                if tier == "HIGH" and days_left <= 1 and len(done) >= cap and not any(r.channel == "FAMILY_WHATSAPP" for r in prior):
                    for fc in db.scalars(select(FamilyContact).where(FamilyContact.user_id == user.id, FamilyContact.consented.is_(True))):
                        text = (f"Lifeline alert for {user.name or 'your family member'}: {o.biller_raw} is due "
                                f"{'today' if days_left == 0 else 'tomorrow'} and hasn't been acknowledged.")[:400]
                        _deliver(db, user, o, "FAMILY_WHATSAPP", tier, stage, 1, now, text, simulated, res)
                        res.family += 1
                continue
        if quiet:
            if not any(r.stage == stage and r.status == "SKIPPED_QUIET_HOURS" for r in prior):
                db.add(Reminder(obligation_id=o.id, user_id=user.id, channel="IN_APP", tier=tier, stage=stage,
                                attempt_no=len(done) + 1, scheduled_for=now, status="SKIPPED_QUIET_HOURS",
                                message="Held until morning (quiet hours).", simulated=simulated))
                res.skipped += 1
            continue
        attempt = len(done) + 1
        text = message_for(o, c, days_left)
        channels = LADDER[tier][d] if attempt == 1 else ("IN_APP", "PUSH", "WHATSAPP")
        for ch in channels:
            status = _deliver(db, user, o, ch, tier, stage, attempt, now, text, simulated, res)
            if ch == "WHATSAPP" and status == "SKIPPED_WINDOW_CLOSED" and "PUSH" not in channels:
                _deliver(db, user, o, "PUSH", tier, stage, attempt, now, text, simulated, res)
    db.flush()
    return res


def acknowledge(db: Session, o: Obligation, ack: str, now: datetime | None = None) -> None:
    """Record PAID / SNOOZE_15 / SNOOZE_30 / DISMISS on outstanding reminders of this bill."""
    now = now or datetime.now(timezone.utc)
    for r in db.scalars(select(Reminder).where(Reminder.obligation_id == o.id, Reminder.ack_type.is_(None))):
        r.ack_type, r.ack_at = ack, now


def latest_reminded(db: Session, user: User) -> Obligation | None:
    r = db.scalar(select(Reminder).join(Obligation, Obligation.id == Reminder.obligation_id).where(
        Reminder.user_id == user.id, Obligation.status.in_(OPEN)).order_by(Reminder.scheduled_for.desc()))
    return db.get(Obligation, r.obligation_id) if r else None


def simulate_days(db: Session, user: User, days: int) -> list[dict]:
    """Fast-forward: run the 09:00, 12:00, 15:00 and 18:00 IST ticks for each of the next N days."""
    start = datetime.now(tz()).date()
    out = []
    for i in range(days):
        day_res = TickResult()
        for hh in (9, 12, 15, 18):
            at = datetime.combine(start + timedelta(days=i), time(hh, 0), tzinfo=tz()).astimezone(timezone.utc)
            r = tick(db, user, at, simulated=True)
            for k, v in r.as_dict().items():
                setattr(day_res, k, getattr(day_res, k) + v)
        out.append({"date": (start + timedelta(days=i)).isoformat(), **day_res.as_dict()})
    return out
