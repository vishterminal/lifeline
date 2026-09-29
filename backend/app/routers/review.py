"""Read side of what the inputs produced: timeline, confirmations, flagged items,
ingest log. (Ranking by ₹ consequence arrives with the output side.)"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.errors import ApiError
from app.models import FlaggedItem, IngestEvent, Obligation, PendingConfirmation, User
from app.schemas import ConfirmationOut, FlaggedOut, IngestEventOut, ObligationOut, ResolveIn
from app.services import pipeline
from app.services.billers import normalize
from app.timeutil import now_utc

router = APIRouter(tags=["review"])


def _own(db: Session, model, obj_id: str, user: User):
    obj = db.get(model, obj_id)
    if obj is None or obj.user_id != user.id:  # 404 either way: don't reveal others' rows
        raise ApiError(404, "Not found")
    return obj


@router.get("/obligations", response_model=list[ObligationOut])
def list_obligations(status: str | None = Query(None), origin: str | None = Query(None),
                     user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Obligation).where(Obligation.user_id == user.id)
    if status:
        q = q.where(Obligation.status.in_([s.strip().upper() for s in status.split(",")]))
    if origin:
        q = q.where(Obligation.origin == origin.upper())
    return list(db.scalars(q.order_by(Obligation.due_date, Obligation.created_at)))


@router.get("/obligations/{obligation_id}", response_model=ObligationOut)
def get_obligation(obligation_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _own(db, Obligation, obligation_id, user)


@router.get("/confirmations", response_model=list[ConfirmationOut])
def list_confirmations(status: str = "PENDING", user: User = Depends(current_user), db: Session = Depends(get_db)):
    return list(db.scalars(select(PendingConfirmation).where(
        PendingConfirmation.user_id == user.id, PendingConfirmation.status == status.upper()
    ).order_by(PendingConfirmation.created_at.desc())))


@router.post("/confirmations/{conf_id}/resolve")
def resolve_confirmation(conf_id: str, body: ResolveIn, user: User = Depends(current_user),
                         db: Session = Depends(get_db)):
    conf = _own(db, PendingConfirmation, conf_id, user)
    if conf.status != "PENDING":
        raise ApiError(409, "Already resolved")
    if body.action == "reject":
        conf.status, conf.resolved_at = "REJECTED", now_utc()
        db.commit()
        return {"status": conf.status}

    fields = dict(conf.draft.get("fields") or {})
    if body.fields:
        for k, v in body.fields.model_dump(exclude_unset=True).items():
            fields[k] = v
    # Mismatched values are never auto-picked: the user must send the value.
    for m in conf.draft.get("mismatches") or []:
        key = {"biller_norm": "biller"}.get(m, m)
        if not body.fields or key not in body.fields.model_fields_set:
            raise ApiError(422, f"Choose a value for '{key}' — the two readers disagreed",
                           details={"field": key, "candidates": conf.draft.get("candidates")})
    if not fields.get("due_date"):
        raise ApiError(422, "A date is required", details={"field": "due_date"})
    kind = fields.get("message_kind") or "DUE_NOTICE"
    if fields.get("amount") in (None, "") and kind in pipeline.AMOUNT_REQUIRED_KINDS:
        raise ApiError(422, "An amount is required", details={"field": "amount"})
    if body.fields and "biller" in body.fields.model_fields_set and fields.get("biller"):
        match = normalize(fields["biller"], db)
        fields["biller_norm"] = match.canonical if match else None
        if match and match.alias and not (body.fields.type):
            fields["type"] = match.alias.default_type
    trust = conf.draft.get("trust") or {}
    res = pipeline.commit(db, user.id, fields, source_kind=conf.source_kind, origin=conf.origin,
                          trust_label=trust.get("label", "NOT_APPLICABLE"), trust_score=trust.get("score"),
                          confidence=1.0, agreed=True, user_confirmed=True)
    conf.status, conf.resolved_at, conf.obligation_id = "CONFIRMED", now_utc(), res.obligation_id
    db.commit()
    return {"status": conf.status, **res.as_dict()}


@router.get("/flagged", response_model=list[FlaggedOut])
def list_flagged(include_dismissed: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(FlaggedItem).where(FlaggedItem.user_id == user.id)
    if not include_dismissed:
        q = q.where(FlaggedItem.dismissed.is_(False))
    return list(db.scalars(q.order_by(FlaggedItem.created_at.desc())))


@router.post("/flagged/{item_id}/dismiss")
def dismiss_flagged(item_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = _own(db, FlaggedItem, item_id, user)
    item.dismissed = True
    db.commit()
    return {"status": "dismissed"}


@router.get("/ingest-events", response_model=list[IngestEventOut])
def ingest_events(limit: int = Query(50, ge=1, le=500), user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    return list(db.scalars(select(IngestEvent).where(IngestEvent.user_id == user.id)
                           .order_by(IngestEvent.received_at.desc()).limit(limit)))
