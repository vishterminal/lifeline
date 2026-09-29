"""Twilio WhatsApp sandbox (spec F4).

Inbound replies use TwiML in the webhook response (always inside the 24-hour window).
Outbound reminders use send_whatsapp(); the reminder engine checks the window first.
"""
from __future__ import annotations

import logging
import re
from xml.sax.saxutils import escape

import httpx

from app.config import get_settings

log = logging.getLogger("lifeline.whatsapp")

def send_whatsapp(to_e164: str, text: str) -> bool:
    """Outbound WhatsApp via Twilio (live only)."""
    s = get_settings()
    if not s.twilio_live:
        return False
    try:
        from twilio.rest import Client

        Client(s.twilio_account_sid, s.twilio_auth_token).messages.create(
            from_=s.twilio_whatsapp_from, to=f"whatsapp:{to_e164}", body=text[:1500])
        return True
    except Exception as e:  # never crash the reminder tick
        log.warning("whatsapp send failed: %s", type(e).__name__)
        return False


COMMAND_RE = re.compile(r"^\s*(paid(?:\s+\S+)?|15|30|help|what'?s due|whats due|dismiss)\s*$", re.I)


def validate_signature(url: str, params: dict, signature: str | None) -> bool:
    s = get_settings()
    if not s.twilio_auth_token:
        # No token configured: only acceptable in mock connector mode.
        return s.connector_mode == "mock"
    if not signature:
        return False
    from twilio.request_validator import RequestValidator

    return RequestValidator(s.twilio_auth_token).validate(url, params, signature)


def phone_from_twilio(value: str | None) -> str | None:
    if not value:
        return None
    v = value.removeprefix("whatsapp:").strip()
    return v if re.fullmatch(r"\+[1-9]\d{6,14}", v) else None


def is_command(body: str | None) -> bool:
    return bool(body and COMMAND_RE.match(body))


def twiml(message: str | None) -> str:
    if not message:
        return '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{escape(message)}</Message></Response>'


def download_media(url: str, max_bytes: int = 10 * 1024 * 1024) -> tuple[bytes, str]:
    """Fetch forwarded media with Twilio credentials (media URLs require auth)."""
    s = get_settings()
    auth = (s.twilio_account_sid, s.twilio_auth_token) if s.twilio_account_sid else None
    with httpx.Client(timeout=20.0, follow_redirects=True) as c:
        r = c.get(url, auth=auth)
        r.raise_for_status()
        if len(r.content) > max_bytes:
            raise ValueError("media too large")
        return r.content, r.headers.get("content-type", "application/octet-stream").split(";")[0]
