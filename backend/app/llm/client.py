"""LLM adapter: live Anthropic API or deterministic mock (LLM_MODE).

LLM output is data only: callers validate it and never execute it as an action.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.config import get_settings

log = logging.getLogger("lifeline.llm")

# Models that accept the server-side refusal fallback ("default" routing).
_FALLBACK_MODELS: set[str] = set()


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(self) -> None:
        s = get_settings()
        import anthropic

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(
            api_key=s.anthropic_api_key, timeout=s.llm_timeout_seconds, max_retries=1
        )
        self.model = s.anthropic_model

    def json_call(self, system: str, content: list[dict] | str, schema: dict, max_tokens: int = 2000) -> dict[str, Any]:
        """One structured-output call. Raises LLMError on any failure."""
        kwargs: dict[str, Any] = dict(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        )
        if self.model in _FALLBACK_MODELS:
            kwargs["extra_headers"] = {"anthropic-beta": "server-side-fallback-2026-07-01"}
            kwargs["extra_body"] = {"fallbacks": "default"}
        try:
            resp = self._client.messages.create(**kwargs)
        except self._anthropic.APITimeoutError as e:
            raise LLMError("timeout") from e
        except self._anthropic.RateLimitError as e:
            raise LLMError("rate_limited") from e
        except self._anthropic.APIStatusError as e:
            raise LLMError(f"api_status_{e.status_code}") from e
        except self._anthropic.APIConnectionError as e:
            raise LLMError("connection") from e
        if resp.stop_reason == "refusal":
            raise LLMError("refusal")
        if resp.stop_reason == "max_tokens":
            raise LLMError("max_tokens")
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMError("invalid_json") from e


_client: LLMClient | None = None


def get_llm() -> LLMClient | None:
    """Live client, or None when LLM_MODE=mock / keys missing."""
    global _client
    if not get_settings().llm_live:
        return None
    if _client is None:
        _client = LLMClient()
    return _client
