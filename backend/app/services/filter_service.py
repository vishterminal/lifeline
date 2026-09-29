"""R-FILTER: rule-based prefilter before any AI call (spec F6)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import yaml

from app.config import DATA_DIR
from app.models import BillerAlias
from app.services.billers import by_sender_id


@lru_cache
def _config() -> dict:
    return yaml.safe_load((DATA_DIR / "filter_config.yaml").read_text(encoding="utf-8"))


@dataclass
class FilterResult:
    keep: bool
    outcome: str | None = None  # DROPPED_OTP | DROPPED_NOT_BILL
    reason: str | None = None


_CODE = re.compile(r"(?<!\d)\d{4,8}(?!\d)")


def is_otp(text: str) -> bool:
    low = text.lower()
    hits = [p for p in _config()["otp_patterns"] if re.search(p, low)]
    if not hits:
        return False
    # "OTP" / "one time password" alone are decisive; "do not share" needs a code
    # nearby so that e.g. a bill saying "do not share your account number" survives.
    strong = any(re.search(p, low) for p in (r"\botp\b", r"one[\s-]?time[\s-]?password", r"verification code"))
    return strong or bool(_CODE.search(text))


def has_bill_keyword(text: str) -> bool:
    low = text.lower()
    return any(re.search(rf"(?<![a-z]){re.escape(k)}(?![a-z])", low) for k in _config()["bill_keywords"])


def prefilter(text: str, sender: str | None, aliases: list[BillerAlias]) -> FilterResult:
    if is_otp(text):
        return FilterResult(False, "DROPPED_OTP", "otp_pattern")
    known_sender = by_sender_id(sender, aliases) is not None or (
        sender is not None and sender.upper() in {s.upper() for s in _config().get("known_sender_ids") or []}
    )
    if known_sender or has_bill_keyword(text):
        return FilterResult(True)
    return FilterResult(False, "DROPPED_NOT_BILL", "no_bill_keywords_unknown_sender")
