from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.config import get_settings


def tz() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def today_local() -> date:
    """User-facing 'today' (Asia/Kolkata by default)."""
    return datetime.now(tz()).date()
