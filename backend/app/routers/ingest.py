from __future__ import annotations

import json
import logging
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.errors import ApiError
from app.models import User
from app.ratelimit import ingest_key, ingest_limit, limiter
from app.schemas import ManualIn
from app.services import pipeline, sms_service, statement_service, upload_service, whatsapp_inbound, whatsapp_service
from app.config import get_settings
from app.services.billers import normalize
from app.timeutil import now_utc

log = logging.getLogger("lifeline.ingest")
router = APIRouter(tags=["ingest"])


# --- SMS forwarder webhook ----------------------------------------------------------
@router.post("/ingest/sms")
@limiter.limit(ingest_limit, key_func=ingest_key)
async def ingest_sms(request: Request, db: Session = Depends(get_db)):
    src = sms_service.resolve_token(db, request.headers.get("x-ingest-token"))
    if src is None:
        return JSONResponse({"error": {"code": "UNAUTHORIZED", "message": "Bad ingest token", "details": {}}},
                            status_code=401)
    ctype = request.headers.get("content-type", "")
    try:
        if "json" in ctype:
            data = await request.json()
        else:
            form = await request.form()
            data = dict(form)
            if not data:  # some forwarders send JSON with a text/plain content type
                data = json.loads((await request.body()) or b"{}")
    except Exception:
        data = {}
    payload = sms_service.map_payload(data if isinstance(data, dict) else {})
    if not payload.get("text"):
        # Unparseable: accept so the forwarder doesn't retry forever (log only).
        log.info("sms webhook: unparseable payload")
        return {"status": "dropped"}
    user = db.get(User, src.user_id)
    res = pipeline.process_incoming(db, user, "SMS", str(payload["text"]), pipeline.IncomingMeta(
        sender=str(payload.get("sender") or "") or None,
        received_at=sms_service.parse_received_at(payload.get("received_at"))))
    src.last_received_at = now_utc()
    db.commit()
    return {"status": "dropped" if res.outcome.startswith("DROPPED") else "accepted"}


# --- Twilio WhatsApp webhook -----------------------------------------------------------
@router.post("/webhooks/twilio/whatsapp")
@limiter.limit(ingest_limit)
async def twilio_whatsapp(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    params = {k: v for k, v in form.items()}
    url = get_settings().public_base_url.rstrip("/") + request.url.path
    if request.url.query:
        url += "?" + request.url.query
    if not whatsapp_service.validate_signature(url, params, request.headers.get("x-twilio-signature")):
        return Response(status_code=403)
    reply = whatsapp_inbound.handle_inbound(db, params)
    db.commit()
    return Response(whatsapp_service.twiml(reply), media_type="application/xml")


# --- Upload / manual / statement ----------------------------------------------------
@router.post("/ingest/upload")
async def ingest_upload(file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    data = await file.read(upload_service.MAX_BYTES + 1)
    try:
        res = upload_service.process_upload(db, user, data, file.content_type)
    except upload_service.TooLarge:
        raise ApiError(413, "File is larger than 10 MB")
    except upload_service.UnsupportedType:
        raise ApiError(415, "Only PDF, JPG and PNG files are supported")
    db.commit()
    return res.as_dict()


@router.post("/ingest/manual", status_code=201)
def ingest_manual(body: ManualIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    match = normalize(body.biller, db)
    otype = body.type if body.type != "OTHER" or not (match and match.alias) else match.alias.default_type
    fields = {
        "biller": body.biller.strip(), "biller_norm": match.canonical if match else None, "type": otype,
        "amount": body.amount, "due_date": body.due_date, "vehicle_ref": body.vehicle_ref,
        "message_kind": "RENEWAL_NOTICE" if body.recurring else "DUE_NOTICE", "recurrence_hint": body.recurring,
    }
    if body.review:
        draft = {**fields, "amount": str(body.amount) if body.amount is not None else None,
                 "due_date": body.due_date.isoformat()}
        conf = pipeline.create_confirmation(db, user.id, "MANUAL", "REAL", "MANUAL_ENTRY", draft)
        db.commit()
        return {"outcome": "NEEDS_CONFIRMATION", "confirmation_id": conf.id, "obligation": None}
    res = pipeline.commit(db, user.id, fields, source_kind="MANUAL", trust_label="NOT_APPLICABLE", confidence=1.0, agreed=True)
    db.commit()
    from app.models import Obligation
    from app.schemas import ObligationOut

    return {"outcome": res.outcome, "obligation": ObligationOut.model_validate(db.get(Obligation, res.obligation_id))}


@router.post("/ingest/statement")
async def ingest_statement(file: UploadFile = File(...), current_balance: str | None = Form(None),
                           user: User = Depends(current_user), db: Session = Depends(get_db)):
    data = await file.read(upload_service.MAX_BYTES + 1)
    if len(data) > upload_service.MAX_BYTES:
        raise ApiError(413, "File is larger than 10 MB")
    name = (file.filename or "").lower()
    if not (name.endswith(".csv") or name.endswith(".pdf") or data[:5] == b"%PDF-"):
        raise ApiError(415, "Upload a CSV (preferred) or PDF bank statement")
    bal = None
    if current_balance not in (None, ""):
        try:
            bal = Decimal(current_balance)
        except InvalidOperation:
            raise ApiError(422, "current_balance must be a number")
        if bal < 0:
            raise ApiError(422, "current_balance must be ≥ 0")
    result = statement_service.import_statement(db, user, data, file.filename, bal)
    db.commit()
    return result
