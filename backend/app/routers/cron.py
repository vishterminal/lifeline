"""Scheduled jobs for serverless hosting (Vercel Cron), where no background scheduler runs:
poll every connected Gmail inbox and run the reminder engine. Protected by CRON_SECRET."""
from __future__ import annotations

import hmac

from fastapi import APIRouter, Request

from app.config import get_settings
from app.errors import ApiError
from app.jobs import scheduler

router = APIRouter(prefix="/cron", tags=["cron"])


@router.get("/tick")
def tick(request: Request):
    secret = get_settings().cron_secret
    given = request.headers.get("authorization", "")
    if not secret or not hmac.compare_digest(given, f"Bearer {secret}"):
        raise ApiError(401, "Not allowed")
    scheduler.gmail_poll()
    scheduler.reminder_tick()
    return {"status": "ok"}
