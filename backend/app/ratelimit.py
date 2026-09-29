from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings


def _ingest_key(request: Request) -> str:
    tok = request.headers.get("x-ingest-token", "")
    return "tok:" + tok.split(".", 1)[0] if tok else get_remote_address(request)


limiter = Limiter(key_func=get_remote_address)


def auth_limit() -> str:
    return get_settings().rate_limit_auth


def ingest_limit() -> str:
    return get_settings().rate_limit_ingest


ingest_key = _ingest_key
