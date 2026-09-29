"""Biller name normalization via the biller_aliases table.

`NETFLIX.COM`, `Netflix India` -> `netflix`. Unknown names get a slug.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BillerAlias


@dataclass
class BillerMatch:
    canonical: str
    display: str
    alias: BillerAlias | None


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s[:100] or "unknown"


def all_aliases(db: Session) -> list[BillerAlias]:
    return list(db.scalars(select(BillerAlias)))


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9. ]+", " ", text.lower())).strip()


def find_in_text(text: str, aliases: list[BillerAlias]) -> BillerAlias | None:
    """Longest alias found as a whole word/phrase in the text."""
    hay = f" {_clean(text)} "
    best: tuple[int, BillerAlias] | None = None
    for a in aliases:
        for name in [a.canonical_name.replace("_", " "), *a.aliases]:
            n = _clean(name)
            if n and re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", hay):
                if best is None or len(n) > best[0]:
                    best = (len(n), a)
    return best[1] if best else None


def normalize(name: str | None, db: Session, aliases: list[BillerAlias] | None = None) -> BillerMatch | None:
    if not name or not name.strip():
        return None
    aliases = aliases if aliases is not None else all_aliases(db)
    hit = find_in_text(name, aliases)
    if hit:
        return BillerMatch(hit.canonical_name, hit.display_name, hit)
    return BillerMatch(slugify(name), name.strip()[:200], None)


def by_sender_id(sender: str | None, aliases: list[BillerAlias]) -> BillerAlias | None:
    """Match an Indian SMS header like 'VM-TNEBLT' against configured sender IDs."""
    if not sender:
        return None
    s = sender.upper()
    core = s.split("-", 1)[-1]
    for a in aliases:
        for sid in a.sender_ids or []:
            if sid.upper() in (s, core):
                return a
    return None


def by_domain(domain: str | None, aliases: list[BillerAlias]) -> BillerAlias | None:
    if not domain:
        return None
    d = domain.lower()
    for a in aliases:
        for od in a.official_domains or []:
            od = od.lower()
            if d == od or d.endswith("." + od):
                return a
    return None
