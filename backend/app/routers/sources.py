from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import current_user
from app.errors import ApiError
from app.models import ConnectedSource, Consent, User
from app.schemas import WhatsAppLinkIn
from app.security import generate_ingest_token
from app.services import gmail_service
from app.timeutil import now_utc

router = APIRouter(prefix="/sources", tags=["sources"])

SMS_CHECKLIST = [
    "Android only. Install a free SMS forwarder app (an open-source 'SMS Forwarder' or MacroDroid free tier).",
    "Grant it SMS permission.",
    "Filter: bank / utility / telecom sender IDs, and words: due, bill, debited, renewal, premium.",
    "Exclude any message containing OTP.",
    "Action: HTTP POST (JSON) to the webhook URL below with header X-Ingest-Token: <your token>.",
    'Body: {"sender": "<sender>", "text": "<message>", "received_at": "<timestamp>"}',
    "Turn OFF battery optimization for the forwarder (Xiaomi/Oppo/Vivo phones kill background apps).",
    "Send yourself a test bill SMS and check 'last SMS received' here.",
]
SMS_CAVEAT = ("Demo-only privacy caveat: the third-party forwarder app can read your SMS. "
              "Lifeline stores only extracted bill details, never the message.")


def _source(db: Session, user: User, kind: str) -> ConnectedSource | None:
    return db.scalar(select(ConnectedSource).where(ConnectedSource.user_id == user.id, ConnectedSource.kind == kind))


@router.get("")
def list_sources(user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = get_settings()
    gm, sms, wa = (_source(db, user, k) for k in ("GMAIL", "SMS", "WHATSAPP"))
    window_open = bool(user.whatsapp_last_inbound_at and
                       now_utc() - _aware(user.whatsapp_last_inbound_at) < timedelta(hours=24))
    return [
        {"kind": "GMAIL", "mode": "live" if gmail_service.is_live() else "mock",
         "status": gm.status if gm else "DISCONNECTED", "gmail_address": gm.gmail_address if gm else None,
         "last_sync_at": gm.last_sync_at if gm else None, "last_error": gm.last_error if gm else None},
        {"kind": "SMS", "status": sms.status if sms else "DISCONNECTED",
         "webhook_url": f"{s.public_base_url}/api/ingest/sms", "has_token": bool(sms and sms.ingest_token_hash),
         "last_received_at": sms.last_received_at if sms else None, "checklist": SMS_CHECKLIST, "caveat": SMS_CAVEAT},
        {"kind": "WHATSAPP", "mode": "live" if s.twilio_live else "mock",
         "status": wa.status if wa else ("LINKED" if user.phone_e164 else "DISCONNECTED"),
         "phone_e164": user.phone_e164, "sandbox_number": s.twilio_whatsapp_from.removeprefix("whatsapp:"),
         "sandbox_join_code": s.twilio_sandbox_join_code,
         "window_open": window_open, "last_inbound_at": user.whatsapp_last_inbound_at,
         "webhook_url": f"{s.public_base_url}/api/webhooks/twilio/whatsapp",
         "instructions": ["Save the Twilio sandbox number in your contacts.",
                          "Send it the sandbox join code (shown in the Twilio console) once.",
                          "Forward any bill text, photo or PDF to it.",
                          "Send any message at least once a day to keep the 24-hour window open."]},
    ]


def _aware(dt):
    from datetime import timezone

    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# --- Gmail --------------------------------------------------------------------
@router.get("/gmail/connect")
def gmail_connect(user: User = Depends(current_user), db: Session = Depends(get_db)):
    url = gmail_service.build_auth_url(db, user)
    db.commit()
    return {"auth_url": url, "mode": "live" if gmail_service.is_live() else "mock"}


@router.get("/gmail/callback")
def gmail_callback(code: str | None = None, state: str | None = None, error: str | None = None,
                   db: Session = Depends(get_db)):
    front = get_settings().front_url("")
    if error:
        return RedirectResponse(f"{front}/connect?gmail=denied")
    try:
        gmail_service.complete_oauth(db, code or "", state or "")
        db.commit()
    except PermissionError:
        db.commit()
        raise ApiError(403, "Invalid or expired sign-in state. Start Connect Gmail again.")
    except ValueError:
        raise ApiError(422, "Missing code or state")
    except gmail_service.UpstreamError:
        db.commit()
        return RedirectResponse(f"{front}/connect?gmail=error")
    return RedirectResponse(f"{front}/connect?gmail=connected")


@router.post("/gmail/sync")
def gmail_sync(user: User = Depends(current_user), db: Session = Depends(get_db)):
    src = gmail_service.get_source(db, user)
    if src.status == "DISCONNECTED":
        raise ApiError(409, "Gmail is not connected")
    result = gmail_service.sync(db, user)
    db.commit()
    return result


@router.delete("/gmail")
def gmail_disconnect(user: User = Depends(current_user), db: Session = Depends(get_db)):
    gmail_service.disconnect(db, user)
    db.commit()
    return {"status": "DISCONNECTED"}


# --- SMS ----------------------------------------------------------------------
@router.post("/sms/token")
def sms_token(user: User = Depends(current_user), db: Session = Depends(get_db)):
    src = _source(db, user, "SMS")
    if src is None:
        src = ConnectedSource(user_id=user.id, kind="SMS")
        db.add(src)
        db.add(Consent(user_id=user.id, kind="SMS"))
    token, prefix, digest = generate_ingest_token()
    src.ingest_token_prefix, src.ingest_token_hash = prefix, digest
    src.status, src.consented_at = "CONNECTED", src.consented_at or now_utc()
    db.commit()
    return {"token": token, "webhook_url": f"{get_settings().public_base_url}/api/ingest/sms",
            "note": "Shown once. Generating a new token invalidates the old one."}


@router.delete("/sms")
def sms_disconnect(user: User = Depends(current_user), db: Session = Depends(get_db)):
    src = _source(db, user, "SMS")
    if src:
        src.ingest_token_hash = src.ingest_token_prefix = None
        src.status = "DISCONNECTED"
    db.commit()
    return {"status": "DISCONNECTED"}


# --- WhatsApp -----------------------------------------------------------------
@router.put("/whatsapp")
def whatsapp_link(body: WhatsAppLinkIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    taken = db.scalar(select(User.id).where(User.phone_e164 == body.phone_e164, User.id != user.id))
    if taken:
        raise ApiError(409, "That phone number is linked to another account")
    user.phone_e164 = body.phone_e164
    src = _source(db, user, "WHATSAPP")
    if src is None:
        db.add(ConnectedSource(user_id=user.id, kind="WHATSAPP", status="DISCONNECTED", consented_at=now_utc()))
        db.add(Consent(user_id=user.id, kind="WHATSAPP"))
    db.commit()
    return {"status": "LINKED", "phone_e164": user.phone_e164,
            "next": "Send the sandbox join code, then forward a bill to the sandbox number."}
