"""Web push (VAPID). Sends to every browser the user subscribed; expired
subscriptions (404/410) are removed. Without VAPID keys push stays simulated."""
from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import PushSubscription, User

log = logging.getLogger("lifeline.push")


def enabled() -> bool:
    return get_settings().push_enabled


def send(db: Session, user: User, title: str, body: str, url: str = "/reminders") -> int:
    """Returns how many browsers accepted the notification."""
    s = get_settings()
    if not s.push_enabled:
        return 0
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        return 0
    ok = 0
    for sub in list(db.scalars(select(PushSubscription).where(PushSubscription.user_id == user.id))):
        try:
            webpush(
                subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                data=json.dumps({"title": title, "body": body[:240], "url": url}),
                vapid_private_key=s.vapid_private_key,
                vapid_claims={"sub": s.vapid_subject},
                timeout=10,
            )
            ok += 1
        except WebPushException as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (404, 410):
                db.delete(sub)  # browser unsubscribed
            log.warning("push failed status=%s", status)
        except Exception as e:  # never break the reminder tick
            log.warning("push error %s", type(e).__name__)
    return ok
