"""Deterministic stand-in for AI-1 when LLM_MODE=mock.

It is intentionally a *different* heuristic from the rule extractor (so the
reconcile step is meaningful), plus a few scripted fixtures:
  * text containing "[mock:llm-fail]"      -> raises (LLM failure path)
  * text containing "[mock:llm-invalid]"   -> returns malformed JSON
  * text containing "[mock:amount=<n>]"     -> reports that amount (mismatch demo)
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.llm.client import LLMError
from app.models import BillerAlias
from app.services.extraction import rule_extractor


def mock_extract(redacted_text: str, aliases: list[BillerAlias], today: date, sender_name: str | None) -> dict[str, Any] | str:
    if "[mock:llm-fail]" in redacted_text:
        raise LLMError("mock_failure")
    if "[mock:llm-invalid]" in redacted_text:
        return "{not json"
    base = rule_extractor.extract(redacted_text, aliases, today, sender_name)
    data = base.model_dump(mode="json")
    forced = re.search(r"\[mock:amount=([0-9.]+)\]", redacted_text)
    if forced:
        data["amount"] = float(forced.group(1))
    # The "LLM" is somewhat more confident than rules when it found the core fields.
    data["confidence"] = 0.9 if data["amount"] and data["due_date"] else 0.6
    data["notes"] = "mock-llm"
    return data
