"""In-process scheduler. Input side only: gmail_poll. (reminder_tick and
overdue_sweep belong to the output side.)"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import ConnectedSource, User
from app.services import gmail_service

log = logging.getLogger("lifeline.jobs")
_scheduler: BackgroundScheduler | None = None


def gmail_poll() -> None:
    with SessionLocal() as db:
        srcs = list(db.scalars(select(ConnectedSource).where(
            ConnectedSource.kind == "GMAIL", ConnectedSource.status.in_(("CONNECTED", "ERROR")))))
        for src in srcs:
            user = db.get(User, src.user_id)
            try:
                result = gmail_service.sync(db, user)
                db.commit()
                log.info("gmail poll user=%s fetched=%s", user.id, result.get("fetched"))
            except Exception as e:
                db.rollback()
                log.warning("gmail poll failed user=%s: %s", src.user_id, type(e).__name__)


def reminder_tick() -> None:
    from app.services import reminder_service

    with SessionLocal() as db:
        for user in db.scalars(select(User)):
            try:
                reminder_service.tick(db, user)
                db.commit()
            except Exception as e:
                db.rollback()
                log.warning("reminder tick failed user=%s: %s", user.id, type(e).__name__)


def start() -> None:
    global _scheduler
    s = get_settings()
    if not s.enable_scheduler or _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone=s.timezone)
    _scheduler.add_job(gmail_poll, "interval", minutes=s.gmail_poll_minutes, id="gmail_poll",
                       max_instances=1, coalesce=True)
    _scheduler.add_job(reminder_tick, "interval", minutes=s.reminder_tick_minutes, id="reminder_tick",
                       max_instances=1, coalesce=True)
    _scheduler.start()


def stop() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
