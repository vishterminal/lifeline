"""Demo-input simulators (spec F20, input half): push fixtures through the REAL
pipeline, so the demo survives venue Wi-Fi / missing accounts."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.errors import ApiError
from app.models import User
from app.schemas import SimulateTextIn
from app.services import gmail_service, pipeline, whatsapp_inbound
from app.services.gmail_service import render_fixture_text

router = APIRouter(prefix="/demo", tags=["demo"])

SMS_FIXTURES = {
    "bill": ("VM-TNEBLT", "TNEB: Your electricity bill of Rs.1840.00 is due on {{date:+1}}. Pay to avoid late fee."),
    "otp": ("VM-HDFCBK", "Your OTP is 482913. Do not share it with anyone."),
    "personal": ("+919800000000", "Hey, dinner tonight?"),
    "debit": ("VM-HDFCBK", "Rs.1840.00 debited from A/c XX1234 to TNEB on {{date:+0}}. Avl bal Rs.20,150.00"),
    "insurance": ("VM-ACKOIN", "Two-wheeler insurance for TN09AB1234 expires on {{date:+21}}. Renew now: premium Rs 2,150."),
    "mismatch": ("VM-AIRTEL", "Airtel postpaid bill Rs. 799 due on {{date:+9}}. [mock:amount=899]"),
}
WA_FIXTURES = {
    "bill": "Fwd: TNEB: Your electricity bill of Rs.1840.00 is due on {{date:+1}}. Pay to avoid late fee.",
    "whats_due": "WHAT'S DUE",
    "help": "HELP",
    "paid": "PAID",
}


@router.get("/fixtures")
def fixtures():
    return {"sms": sorted(SMS_FIXTURES), "email": gmail_service.mock_inbox_names() + ["fake_netflix"],
            "whatsapp": sorted(WA_FIXTURES)}


@router.post("/simulate/sms")
def simulate_sms(body: SimulateTextIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.text:
        sender, text = body.sender, body.text
    elif body.fixture in SMS_FIXTURES:
        sender, text = SMS_FIXTURES[body.fixture]
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
        raise ApiError(409, "Link a WhatsApp number first (Sources → WhatsApp)")
    text = body.text or WA_FIXTURES.get(body.fixture or "bill")
    if text is None:
        raise ApiError(422, f"Pick a fixture: {', '.join(WA_FIXTURES)} (or send text)")
    reply = whatsapp_inbound.handle_inbound(db, {"From": f"whatsapp:{user.phone_e164}",
                                                 "Body": render_fixture_text(text), "NumMedia": "0"}, origin="DEMO")
    db.commit()
    return {"reply": reply}
