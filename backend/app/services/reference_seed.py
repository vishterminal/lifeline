"""Idempotent loader for global reference data (upsert by natural key)."""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import DATA_DIR
from app.models import BillerAlias

_FIELDS = (
    "display_name", "aliases", "category", "default_type", "official_domains",
    "sender_ids", "official_account_url", "behavior", "billing_cycle_days", "reference_verified",
)


def load_reference_seeds(db: Session) -> int:
    data = json.loads((DATA_DIR / "biller_aliases_seed.json").read_text(encoding="utf-8"))
    count = 0
    for row in data["billers"]:
        existing = db.scalar(select(BillerAlias).where(BillerAlias.canonical_name == row["canonical_name"]))
        if existing is None:
            existing = BillerAlias(canonical_name=row["canonical_name"])
            db.add(existing)
        for f in _FIELDS:
            setattr(existing, f, row.get(f))
        count += 1
    db.flush()
    return count
