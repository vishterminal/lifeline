"""Third-party Android SMS-forwarder payload handling (spec F3).

Forwarder apps use different field names, so accept several (IMPLEMENTATION
DECISION; extend FIELD_MAP if your app uses others).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ConnectedSource
from app.security import token_matches

FIELD_MAP = {
    "sender": ("sender", "from", "phone", "address", "number", "originatingAddress", "msg_from"),
    "text": ("text", "message", "body", "msg", "content", "sms", "smsBody"),
    "received_at": ("received_at", "timestamp", "sentStamp", "receivedStamp", "date", "time"),
}


def map_payload(data: dict) -> dict:
    out: dict = {}
    lower = {str(k).lower(): v for k, v in data.items()}
    for field, keys in FIELD_MAP.items():
        for k in keys:
            if k.lower() in lower and lower[k.lower()] not in (None, ""):
                out[field] = lower[k.lower()]
                break
    return out


def parse_received_at(value) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        num = float(value)
        if num > 1e12:  # epoch ms
            num /= 1000
        return datetime.fromtimestamp(num, tz=timezone.utc)
    except (TypeError, ValueError):
        pass
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def resolve_token(db: Session, token: str | None) -> ConnectedSource | None:
    """Find the SMS source for a token of form '<prefix>.<secret>' (constant-time compare)."""
    if not token or "." not in token:
        return None
    prefix = token.split(".", 1)[0]
    src = db.scalar(select(ConnectedSource).where(
        ConnectedSource.kind == "SMS", ConnectedSource.ingest_token_prefix == prefix))
    if src and token_matches(token, src.ingest_token_hash):
        return src
    return None
