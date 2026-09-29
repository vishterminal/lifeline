"""process_incoming(): the single path every input takes (spec Section 10.1).

HASH/DEDUP -> PREFILTER -> REDACT -> EXTRACT A (LLM) + B (rules) -> RECONCILE
-> TRUST -> DECIDE (flag | drop | confirm | paid-detect | save/merge) -> LOG

The raw text lives only in memory for the duration of this call. It is never
persisted and never logged; ingest_events keep a hash and the outcome only.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ChargeEvent, FlaggedItem, IngestEvent, Obligation, PendingConfirmation, User
from app.services import billers, dedup_service, recurring_service, trust_service
from app.services.extraction import llm_extractor, rule_extractor
from app.services.extraction.reconcile import reconcile
from app.services.extraction.types import Extraction
from app.services.filter_service import prefilter
from app.services.redaction_service import redact
from app.timeutil import today_local

log = logging.getLogger("lifeline.pipeline")

MAX_TEXT = 20_000
CONFIDENCE_MIN = 0.6
RECEIPT_KINDS = ("PAYMENT_CONFIRMATION", "RECEIPT")
AMOUNT_REQUIRED_KINDS = ("DUE_NOTICE", "PAYMENT_CONFIRMATION", "RECEIPT")


@dataclass
class IncomingMeta:
    sender: str | None = None  # email address / SMS header / whatsapp number
    sender_name: str | None = None  # display name, used as a biller hint
    auth_results: str | None = None
    links: list[tuple[str, str]] = field(default_factory=list)
    received_at: datetime | None = None
    origin: str = "REAL"  # REAL | DEMO
    skip_new_biller_check: bool = False  # user supplied it themselves (upload)


@dataclass
class PipelineResult:
    outcome: str
    obligation_id: str | None = None
    confirmation_id: str | None = None
    flagged_id: str | None = None
    reason: str | None = None
    summary: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def _log_event(db: Session, user_id: str, source_kind: str, chash: str, res: PipelineResult) -> None:
    db.add(IngestEvent(
        user_id=user_id, source_kind=source_kind, content_hash=chash, outcome=res.outcome,
        obligation_id=res.obligation_id, reference_id=res.confirmation_id or res.flagged_id,
        reason=(res.reason or "")[:300] or None,
    ))


def fmt_inr(amount: Decimal | None) -> str:
    if amount is None:
        return "amount unknown"
    s = f"{amount:,.2f}".rstrip("0").rstrip(".")
    return f"₹{s}"


def _describe(o: Obligation) -> str:
    return f"{o.biller_raw or o.biller_norm or 'Bill'} {fmt_inr(o.amount)} due {o.due_date:%d %b %Y}"


# --------------------------------------------------------------------------------
def process_incoming(db: Session, user: User, source_kind: str, raw_text: str,
                     meta: IncomingMeta | None = None) -> PipelineResult:
    meta = meta or IncomingMeta()
    text = (raw_text or "")[:MAX_TEXT]
    chash = content_hash(text)

    # 1. HASH & DEDUP (idempotent against forwarder/webhook retries)
    seen = db.scalar(select(IngestEvent.id).where(
        IngestEvent.user_id == user.id, IngestEvent.content_hash == chash,
        IngestEvent.outcome != "FAILED").limit(1))
    if seen:
        res = PipelineResult("DUPLICATE", reason="content_hash_seen")
        _log_event(db, user.id, source_kind, chash, res)
        return res

    aliases = billers.all_aliases(db)

    # 2. PREFILTER
    f = prefilter(text, meta.sender, aliases)
    if not f.keep:
        res = PipelineResult(f.outcome, reason=f.reason)
        # OTPs: store nothing but the outcome (not even a hash).
        _log_event(db, user.id, source_kind, "" if f.outcome == "DROPPED_OTP" else chash, res)
        return res

    try:
        with db.begin_nested():
            res = _process_bill(db, user, source_kind, text, meta, aliases)
    except Exception as e:  # never crash the caller; never log the body
        log.exception("pipeline failure (%s)", type(e).__name__)
        res = PipelineResult("FAILED", reason=f"exception:{type(e).__name__}")
    _log_event(db, user.id, source_kind, chash, res)
    return res


def _process_bill(db: Session, user: User, source_kind: str, text: str, meta: IncomingMeta,
                  aliases) -> PipelineResult:
    today = today_local()

    # 3. REDACT (memory only)
    redacted = redact(text)

    # 5. EXTRACT A + B (independent)
    b = rule_extractor.extract(redacted, aliases, today, meta.sender_name)
    a, llm_fail = llm_extractor.extract(redacted, aliases, today, meta.sender_name)
    match_a = billers.normalize(a.biller, db, aliases) if a else None
    match_b = billers.normalize(b.biller, db, aliases)

    # 6. RECONCILE
    rec = reconcile(a, b, match_a.canonical if match_a else None, match_b.canonical if match_b else None, llm_fail)
    fields = rec.fields
    match = match_a or match_b
    if match is None and fields.biller:
        match = billers.normalize(fields.biller, db, aliases)

    # is_bill gate (A decides; rules can only rescue a probable bill into confirmation)
    probable_bill = b.is_bill and b.amount is not None and b.due_date is not None
    if a is not None and not a.is_bill:
        if not probable_bill:
            return PipelineResult("DROPPED_NOT_BILL", reason="llm_not_bill")
        rec.reason = rec.reason or "LOW_CONFIDENCE"
    if a is None and not (b.is_bill and (b.amount is not None or b.due_date is not None)):
        return PipelineResult("DROPPED_NOT_BILL", reason=f"llm_unavailable_rules_no_fields:{llm_fail}")

    fields = fields.model_copy(update={"message_kind": effective_kind(fields.message_kind, fields.due_date, today)})

    # 4. TRUST (after extraction: the cross-check needs the claimed biller)
    trust = trust_service.score(db, user.id, trust_service.TrustInput(
        source_kind=source_kind, sender=meta.sender, auth_results=meta.auth_results, links=meta.links,
        text=redacted, alias=match.alias if match else None, biller_norm=match.canonical if match else None,
        amount=fields.amount, event_date=fields.due_date, message_kind=fields.message_kind,
    ), aliases)

    # 7. DECIDE
    if trust.suspicious:
        item = FlaggedItem(user_id=user.id, origin=meta.origin, source_kind=source_kind,
                           sender=(meta.sender or "")[:320] or None,
                           claimed_biller=match.display if match else fields.biller,
                           claimed_amount=fields.amount, reasons=trust.reasons, risk_score=trust.score)
        db.add(item)
        db.flush()
        return PipelineResult("SUSPICIOUS", flagged_id=item.id, reason=f"risk={trust.score}",
                              summary="Suspicious message — not added. Don't click its links.")

    reason = rec.reason
    if reason is None:
        if fields.due_date is None or (fields.amount is None and fields.message_kind in AMOUNT_REQUIRED_KINDS):
            reason = "MISSING_FIELDS"
        elif rec.confidence < CONFIDENCE_MIN or fields.date_year_inferred or not rule_extractor.sanity_window(fields.due_date, today):
            reason = "LOW_CONFIDENCE"
        elif trust.label == "NEW_BILLER_CONFIRM" and not meta.skip_new_biller_check:
            reason = "NEW_BILLER"
        elif trust.needs_confirmation and trust.label != "NEW_BILLER_CONFIRM":
            reason = "MEDIUM_TRUST"

    draft_fields = {
        "biller": match.display if match else fields.biller,
        "biller_norm": match.canonical if match else None,
        "type": _type_for(fields, match),
        "amount": str(fields.amount) if fields.amount is not None else None,
        "due_date": fields.due_date.isoformat() if fields.due_date else None,
        "vehicle_ref": fields.vehicle_ref,
        "message_kind": fields.message_kind,
        "recurrence_hint": fields.recurrence_hint,
    }
    if reason:
        conf = create_confirmation(db, user.id, source_kind, meta.origin, reason, draft_fields, rec, trust)
        return PipelineResult("NEEDS_CONFIRMATION", confirmation_id=conf.id, reason=reason,
                              summary="Needs your confirmation in the Lifeline app.")

    return commit(db, user.id, draft_fields, source_kind=source_kind, origin=meta.origin,
                  trust_label=trust.label, trust_score=trust.score, confidence=rec.confidence,
                  agreed=rec.agreed)


def effective_kind(kind: str | None, when: date | None, today: date) -> str | None:
    """A receipt can't be dated in the future: a future date on a receipt /
    payment email (e.g. "renews on 29 Oct") is the NEXT charge, i.e. a renewal."""
    if kind in RECEIPT_KINDS and when is not None and when > today + timedelta(days=1):
        return "RENEWAL_NOTICE"
    return kind


def _type_for(fields: Extraction, match) -> str:
    if match and match.alias:
        return match.alias.default_type
    return fields.obligation_type or "OTHER"


def create_confirmation(db: Session, user_id: str, source_kind: str, origin: str, reason: str,
                        draft_fields: dict, rec=None, trust=None) -> PendingConfirmation:
    draft = {
        "fields": draft_fields,
        "candidates": rec.candidates if rec else {},
        "mismatches": rec.mismatches if rec else [],
        "confidence": rec.confidence if rec else None,
        "trust": {"score": trust.score, "label": trust.label, "reasons": trust.reasons} if trust else None,
    }
    conf = PendingConfirmation(user_id=user_id, origin=origin, source_kind=source_kind, draft=draft, reason=reason)
    db.add(conf)
    db.flush()
    return conf


def _as_decimal(v) -> Decimal | None:
    return Decimal(str(v)).quantize(Decimal("0.01")) if v not in (None, "") else None


def _as_date(v) -> date | None:
    if v in (None, ""):
        return None
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def commit(db: Session, user_id: str, f: dict, *, source_kind: str, origin: str = "REAL",
           trust_label: str = "NOT_APPLICABLE", trust_score: int | None = None, confidence: float = 1.0,
           agreed: bool = True, user_confirmed: bool = False) -> PipelineResult:
    """Save a validated item: receipts -> charge/paid-detect/recurring; others -> obligation."""
    amount = _as_decimal(f.get("amount"))
    when = _as_date(f.get("due_date"))
    today = today_local()
    kind = effective_kind(f.get("message_kind") or "DUE_NOTICE", when, today)
    biller_norm = f.get("biller_norm") or (billers.slugify(f["biller"]) if f.get("biller") else None)
    otype = f.get("type") or "OTHER"

    if kind in RECEIPT_KINDS:
        charge = ChargeEvent(user_id=user_id, origin=origin, charge_date=when or today,
                             merchant_norm=biller_norm or "unknown", amount=amount,
                             source="SMS_DEBIT" if source_kind == "SMS" and kind == "PAYMENT_CONFIRMATION" else "RECEIPT")
        db.add(charge)
        db.flush()
        paid = recurring_service.detect_paid(db, user_id, biller_norm, amount, charge.charge_date)
        if paid:
            charge.obligation_id = paid.id
        sub = recurring_service.update_recurring(db, user_id, charge.merchant_norm, f.get("biller"),
                                                 otype if otype == "SUBSCRIPTION" else "SUBSCRIPTION",
                                                 origin, source_kind)
        if paid:
            return PipelineResult("PAID_DETECTED", obligation_id=paid.id,
                                  summary=f"Marked paid: {_describe(paid)}")
        if sub:
            charge.obligation_id = charge.obligation_id or sub.id
            return PipelineResult("SAVED", obligation_id=sub.id, reason="recurring",
                                  summary=f"Tracking renewal: {_describe(sub)}")
        wants_recurring = f.get("recurrence_hint") or otype == "SUBSCRIPTION"
        if wants_recurring:
            interval = 365 if f.get("recurrence_hint") == "ANNUAL" else 30
            nxt = charge.charge_date + timedelta(days=interval)
            cand = {**f, "message_kind": "RENEWAL_NOTICE", "type": "SUBSCRIPTION",
                    "due_date": nxt.isoformat(), "recurrence_hint": "ANNUAL" if interval == 365 else "MONTHLY",
                    "biller_norm": biller_norm}
            if user_confirmed:
                return commit(db, user_id, cand, source_kind=source_kind, origin=origin, trust_label=trust_label,
                              trust_score=trust_score, confidence=confidence, agreed=agreed, user_confirmed=True)
            conf = create_confirmation(db, user_id, source_kind, origin, "RECURRING_CANDIDATE", cand)
            return PipelineResult("NEEDS_CONFIRMATION", confirmation_id=conf.id, reason="RECURRING_CANDIDATE",
                                  summary="Looks like a subscription — confirm the next renewal in the app.")
        return PipelineResult("CHARGE_RECORDED", reason="receipt_no_open_match",
                              summary=f"Noted a payment to {f.get('biller') or 'biller'} {fmt_inr(amount)}")

    if when is None:
        raise ValueError("due_date required to save an obligation")
    fp = dedup_service.fingerprint(biller_norm, otype, amount, when, f.get("vehicle_ref"))
    existing = dedup_service.find_match(db, user_id, fp, biller_norm, otype, when)
    obl_fields = {"amount": amount, "due_date": when, "biller_raw": f.get("biller"),
                  "vehicle_ref": f.get("vehicle_ref"), "extractors_agreed": agreed}
    if existing:
        dedup_service.merge_into(existing, source_kind, obl_fields, confidence)
        db.flush()
        return PipelineResult("SAVED", obligation_id=existing.id, reason="merged",
                              summary=f"Already tracking: {_describe(existing)}")
    rec_hint = f.get("recurrence_hint")
    o = Obligation(
        user_id=user_id, origin=origin, type=otype, biller_raw=f.get("biller"), biller_norm=biller_norm,
        amount=amount, due_date=when, status="OVERDUE" if when < today else "OPEN",
        source_kinds=[source_kind], trust_label=trust_label, trust_score=trust_score,
        confidence=confidence, extractors_agreed=agreed, message_kind=kind,
        vehicle_ref=f.get("vehicle_ref"), fingerprint=fp,
        is_recurring=bool(rec_hint), recurrence_interval_days={"MONTHLY": 30, "ANNUAL": 365}.get(rec_hint),
        next_expected_date=when if rec_hint else None,
    )
    db.add(o)
    db.flush()
    return PipelineResult("SAVED", obligation_id=o.id, summary=f"Added: {_describe(o)}")
