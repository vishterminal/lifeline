"""Handle one inbound WhatsApp message (already signature-checked)."""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ConnectedSource, Obligation, User
from app.services import pipeline, upload_service, whatsapp_service
from app.timeutil import now_utc

log = logging.getLogger("lifeline.whatsapp")

HELP_TEXT = ("Lifeline: forward any bill, renewal notice or receipt (text, photo or PDF) to this number "
             "and it goes on your timeline. Commands: WHAT'S DUE, HELP.")
MAX_MEDIA = 3


def _mark_source(db: Session, user: User) -> None:
    src = db.scalar(select(ConnectedSource).where(ConnectedSource.user_id == user.id, ConnectedSource.kind == "WHATSAPP"))
    if src is None:
        src = ConnectedSource(user_id=user.id, kind="WHATSAPP", consented_at=now_utc())
        db.add(src)
    src.status = "CONNECTED"
    src.last_received_at = now_utc()


def _whats_due(db: Session, user: User) -> str:
    items = list(db.scalars(select(Obligation).where(
        Obligation.user_id == user.id, Obligation.status.in_(("OPEN", "OVERDUE"))
    ).order_by(Obligation.due_date).limit(3)))
    if not items:
        return "Nothing due right now."
    lines = [f"• {pipeline._describe(o)}" for o in items]
    return "Next up:\n" + "\n".join(lines)


def handle_inbound(db: Session, params: dict, media_fetcher=None, origin: str = "REAL") -> str:
    """Returns the reply text (sent back as TwiML)."""
    phone = whatsapp_service.phone_from_twilio(params.get("From"))
    user = db.scalar(select(User).where(User.phone_e164 == phone)) if phone else None
    if user is None:
        return ("This number isn't linked to a Lifeline account yet. Add it under Sources → WhatsApp "
                "in the app, then forward your bills here.")
    user.whatsapp_last_inbound_at = now_utc()  # opens the 24-hour window
    _mark_source(db, user)

    body = (params.get("Body") or "").strip()
    if whatsapp_service.is_command(body):
        cmd = body.upper()
        if cmd.startswith("HELP"):
            return HELP_TEXT
        if "DUE" in cmd:
            return _whats_due(db, user)
        from datetime import timedelta

        from app.services import reminder_service

        o = reminder_service.latest_reminded(db, user)
        if o is None:
            return "Nothing to act on yet - no reminder has been sent to you."
        name = o.biller_raw or o.biller_norm
        if cmd.startswith("PAID"):
            o.status, o.paid_via, o.paid_at = "PAID", "USER_MARKED", now_utc()
            reminder_service.acknowledge(db, o, "PAID")
            return f"Marked {name} as paid. Reminders for it have stopped."
        if cmd.startswith("DISMISS"):
            o.status = "DISMISSED"
            reminder_service.acknowledge(db, o, "DISMISS")
            return f"Dismissed {name}. No more reminders for it."
        minutes = 15 if cmd == "15" else 30
        o.snoozed_until = now_utc() + timedelta(minutes=minutes)
        reminder_service.acknowledge(db, o, f"SNOOZE_{minutes}")
        return f"OK - I'll remind you about {name} again in {minutes} minutes."

    replies: list[str] = []
    try:
        n_media = int(params.get("NumMedia") or 0)
    except ValueError:
        n_media = 0
    fetch = media_fetcher or whatsapp_service.download_media
    for i in range(min(n_media, MAX_MEDIA)):
        url = params.get(f"MediaUrl{i}")
        if not url:
            continue
        try:
            data, ctype = fetch(url)
            res = upload_service.process_upload(db, user, data, ctype, source_kind="WHATSAPP", origin=origin)
            replies.append(res.summary or res.outcome)
        except upload_service.UnsupportedType:
            replies.append("I can read PDFs and JPG/PNG photos only.")
        except upload_service.TooLarge:
            replies.append("That file is over 10 MB.")
        except Exception as e:  # network/Twilio errors: never crash the webhook
            log.warning("media fetch failed: %s", type(e).__name__)
            replies.append("Couldn't download that attachment — please try again.")

    if body:
        res = pipeline.process_incoming(db, user, "WHATSAPP", body, pipeline.IncomingMeta(sender=phone, origin=origin))
        if res.outcome in ("DROPPED_NOT_BILL", "DROPPED_OTP"):
            if not replies:
                replies.append("That doesn't look like a bill, so I ignored it. Send HELP for tips.")
        elif res.outcome == "DUPLICATE":
            replies.append("Already got that one.")
        else:
            replies.append(res.summary or res.outcome)
    return "\n".join(replies) or HELP_TEXT
