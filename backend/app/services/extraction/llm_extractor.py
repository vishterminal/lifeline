"""Extractor A (AI-1). Sends only redacted text. Retries once on invalid output;
any failure returns None so the pipeline degrades to rules-only + confirmation."""
from __future__ import annotations

import json
import logging
from datetime import date

from pydantic import ValidationError

from app.config import get_settings
from app.llm import prompts
from app.llm.client import LLMError, get_llm
from app.llm.mock import mock_extract
from app.models import BillerAlias
from app.services.extraction.types import Extraction

log = logging.getLogger("lifeline.extract")


def _validate(raw) -> Extraction:
    if isinstance(raw, str):
        raw = json.loads(raw)
    if raw.get("recurrence_hint") not in ("MONTHLY", "ANNUAL"):
        raw["recurrence_hint"] = None
    if raw.get("amount") is not None and float(raw["amount"]) <= 0:
        raw["amount"] = None
    raw["confidence"] = max(0.0, min(float(raw.get("confidence") or 0), 1.0))
    return Extraction.model_validate(raw)


def extract(redacted_text: str, aliases: list[BillerAlias], today: date, sender_name: str | None = None) -> tuple[Extraction | None, str | None]:
    """Returns (extraction, failure_reason)."""
    llm = get_llm()
    last_err = None
    for _attempt in range(2):  # one retry on invalid JSON / schema
        try:
            if llm is None:
                raw = mock_extract(redacted_text, aliases, today, sender_name)
            else:
                raw = llm.json_call(
                    prompts.EXTRACT_SYSTEM,
                    prompts.extract_user_message(redacted_text, today.isoformat()),
                    prompts.EXTRACT_SCHEMA,
                )
            return _validate(raw), None
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as e:
            last_err = f"invalid_output:{type(e).__name__}"
            continue
        except LLMError as e:
            reason = str(e)
            if reason == "invalid_json":
                last_err = reason
                continue
            log.warning("llm extraction failed: %s", reason)
            return None, reason
    log.warning("llm extraction invalid after retry: %s", last_err)
    return None, last_err


def extract_from_image(image_bytes: bytes, media_type: str, today: date) -> tuple[Extraction | None, str | None]:
    """Consented vision path (users.allow_cloud_image_processing). Live mode only."""
    import base64

    llm = get_llm()
    if llm is None:
        return None, "vision_unavailable_in_mock_mode"
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                     "data": base64.standard_b64encode(image_bytes).decode()}},
        {"type": "text", "text": f"TODAY: {today.isoformat()}\nExtract the bill details from this image."},
    ]
    for _ in range(2):
        try:
            return _validate(llm.json_call(prompts.EXTRACT_SYSTEM, content, prompts.EXTRACT_SCHEMA)), None
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError):
            continue
        except LLMError as e:
            if str(e) != "invalid_json":
                return None, str(e)
    return None, "invalid_output"


def live_enabled() -> bool:
    return get_settings().llm_live
