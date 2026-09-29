"""Judge / demo mode: sample messages pushed through the REAL pipeline, so every
feature can be tried without Google/Twilio keys, a phone, or internet. Items
created here are labelled DEMO. With real keys the same pipeline runs live."""
from __future__ import annotations

import re
import secrets

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.errors import ApiError
from app.models import ChargeEvent, Payment, Reminder, WaiverDraft, ConnectedSource, FlaggedItem, IngestEvent, Obligation, PendingConfirmation, User
from app.schemas import SimulateTextIn
from app.services import gmail_service, pipeline, whatsapp_inbound
from app.services.gmail_service import render_fixture_text

router = APIRouter(prefix="/demo", tags=["demo"])

# (sender, text, what a judge should expect)
SMS_FIXTURES = {
    "bill": ("VM-TNEBLT", "TNEB: Your electricity bill of Rs.1840.00 is due on {{date:+1}}. Pay to avoid late fee.",
             "Bill → added (asks once: first bill from TNEB)"),
    "otp": ("VM-HDFCBK", "Your OTP is 482913. Do not share it with anyone.",
            "OTP → dropped instantly, nothing stored"),
    "personal": ("+919800000000", "Hey, dinner tonight?", "Personal chat → ignored"),
    "insurance": ("VM-ACKOIN", "Two-wheeler insurance for TN09AB1234 expires on {{date:+21}}. Renew now: premium Rs 2,150.",
                  "Renewal → tracked"),
    "mismatch": ("VM-AIRTEL", "Airtel postpaid bill Rs. 799 due on {{date:+9}}. [mock:amount=899]",
                 "AI and rules read different amounts → you choose"),
    "late": ("VM-BESCOM", "BESCOM: Your electricity bill of Rs. 2,310.00 was due on {{date:-3}}. A late fee of Rs. 100 has been added.",
             "Overdue bill -> Penalty Fighter can draft a waiver"),
    "debit": ("VM-HDFCBK", "Rs.1840.00 debited from A/c XX1234 to TNEB on {{date:+0}}. Avl bal Rs.20,150.00",
              "Payment → matching bill marked paid automatically"),
}
WA_FIXTURES = {
    "bill": "Fwd: TNEB: Your electricity bill of Rs.1840.00 is due on {{date:+1}}. Pay to avoid late fee.",
    "puc": "Fwd: Your PUC certificate for TN09AB1234 expires on {{date:+5}}. Renew at the nearest PUC centre.",
    "whats_due": "WHAT'S DUE",
    "help": "HELP",
}
_MOCK_TAG = re.compile(r"\s*\[mock:[^\]]*\]")


def _display(text: str) -> str:
    return _MOCK_TAG.sub("", render_fixture_text(text))


@router.get("/fixtures")
def fixtures():
    """Sample messages for the phone simulators (rendered with today's dates)."""
    return {
        "sms": [{"id": k, "sender": s, "text": _display(t), "expect": e} for k, (s, t, e) in SMS_FIXTURES.items()],
        "whatsapp": [{"id": k, "text": _display(t)} for k, t in WA_FIXTURES.items()],
        "email": gmail_service.mock_inbox_names(),
    }


@router.get("/sms-status")
def sms_status(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """What happened to each sample SMS for this user (drives the phone simulator):
    not forwarded / waiting for review / handled. Looked up by content hash, the same
    way the pipeline de-duplicates, so it works whoever sent it (phone or 'Run full demo')."""
    out = {}
    for fid, (_, text, _) in SMS_FIXTURES.items():
        h = pipeline.content_hash(render_fixture_text(text))
        ev = db.scalar(select(IngestEvent).where(
            IngestEvent.user_id == user.id, IngestEvent.content_hash == h, IngestEvent.outcome != "DUPLICATE",
        ).order_by(IngestEvent.received_at))
        if ev is None:
            continue
        pending = False
        if ev.outcome == "NEEDS_CONFIRMATION" and ev.reference_id:
            conf = db.get(PendingConfirmation, ev.reference_id)
            pending = conf is not None and conf.status == "PENDING"
        out[fid] = {"outcome": ev.outcome, "confirmation_id": ev.reference_id, "pending": pending}
    return out


@router.get("/inbox")
def inbox(user: User = Depends(current_user)):
    """The sample Gmail inbox a judge 'connects' in demo mode."""
    out = []
    for name in gmail_service.mock_inbox_names():
        m = gmail_service.load_fixture(name)
        preview = re.sub(r"\s+", " ", m.body[len(m.subject):]).strip()
        out.append({"id": name, "from": m.sender_name or m.sender, "address": m.sender, "subject": m.subject,
                    "preview": preview[:140]})
    return out


@router.post("/simulate/sms")
def simulate_sms(body: SimulateTextIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.text:
        sender, text = body.sender or "VM-DEMO", body.text
    elif body.fixture in SMS_FIXTURES:
        sender, text, _ = SMS_FIXTURES[body.fixture]
    else:
        raise ApiError(422, f"Pick a fixture: {', '.join(SMS_FIXTURES)} (or send text)")
    res = pipeline.process_incoming(db, user, "SMS", render_fixture_text(text),
                                    pipeline.IncomingMeta(sender=sender, origin="DEMO"))
    db.commit()
    return res.as_dict()


def _run_email(db: Session, user: User, name: str) -> dict:
    try:
        m = gmail_service.load_fixture(name)
    except FileNotFoundError:
        raise ApiError(404, f"No email fixture '{name}'")
    res = pipeline.process_incoming(db, user, "GMAIL", m.body, pipeline.IncomingMeta(
        sender=m.sender, sender_name=m.sender_name, auth_results=m.auth_results, links=m.links, origin="DEMO"))
    db.commit()
    return res.as_dict()


@router.post("/simulate/email")
def simulate_email(body: SimulateTextIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _run_email(db, user, body.fixture or "tneb_bill")


@router.post("/simulate/fake-email")
def simulate_fake_email(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _run_email(db, user, "fake_netflix")


@router.post("/simulate/whatsapp")
def simulate_whatsapp(body: SimulateTextIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.phone_e164:
        # Demo: give the account a private demo number so the chat simulator just works.
        user.phone_e164 = "+9199" + "".join(secrets.choice("0123456789") for _ in range(8))
        db.flush()
    text = body.text or WA_FIXTURES.get(body.fixture or "bill")
    if text is None:
        raise ApiError(422, f"Pick a fixture: {', '.join(WA_FIXTURES)} (or send text)")
    reply = whatsapp_inbound.handle_inbound(db, {"From": f"whatsapp:{user.phone_e164}",
                                                 "Body": render_fixture_text(text), "NumMedia": "0"}, origin="DEMO")
    db.commit()
    return {"reply": reply, "phone_e164": user.phone_e164}


@router.delete("")
def reset_demo(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Remove only DEMO items so the demo can be run again from scratch. REAL data is untouched."""
    counts = {}
    demo_ids = select(Obligation.id).where(Obligation.user_id == user.id, Obligation.origin == "DEMO")
    db.execute(delete(Payment).where(Payment.obligation_id.in_(demo_ids)))
    db.execute(delete(Reminder).where(Reminder.obligation_id.in_(demo_ids)))
    db.execute(delete(WaiverDraft).where(WaiverDraft.obligation_id.in_(demo_ids)))
    for model in (PendingConfirmation, FlaggedItem, ChargeEvent, Obligation):
        r = db.execute(delete(model).where(model.user_id == user.id, model.origin == "DEMO"))
        counts[model.__tablename__] = r.rowcount
    # The audit log keeps only hashes; clear it so the same sample messages aren't seen as duplicates.
    db.execute(delete(IngestEvent).where(IngestEvent.user_id == user.id))
    gm = db.scalar(select(ConnectedSource).where(ConnectedSource.user_id == user.id, ConnectedSource.kind == "GMAIL"))
    if gm is not None and not gmail_service.is_live(user):
        db.delete(gm)  # sample inbox can be "connected" again
    db.commit()
    return {"removed": counts}
