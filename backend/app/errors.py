"""Uniform error format: {"error": {"code", "message", "details"}} (spec Section 8)."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("lifeline.errors")

CODES = {400: "BAD_REQUEST", 401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 409: "CONFLICT",
         413: "PAYLOAD_TOO_LARGE", 415: "UNSUPPORTED_MEDIA_TYPE", 422: "VALIDATION_ERROR",
         429: "RATE_LIMITED", 502: "UPSTREAM_FAILURE", 500: "INTERNAL"}


class ApiError(Exception):
    def __init__(self, status: int, message: str, code: str | None = None, details: dict | None = None):
        self.status, self.message = status, message
        self.code = code or CODES.get(status, "ERROR")
        self.details = details or {}


def _body(code: str, message: str, details: dict | None = None, request_id: str | None = None) -> dict:
    d = dict(details or {})
    if request_id:
        d.setdefault("request_id", request_id)
    return {"error": {"code": code, "message": message, "details": d}}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(request: Request, exc: ApiError):
        return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=exc.status)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        msg = exc.detail if isinstance(exc.detail, str) else CODES.get(exc.status_code, "Error")
        return JSONResponse(_body(CODES.get(exc.status_code, "ERROR"), msg), status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        fields = [{"loc": [str(p) for p in e.get("loc", [])], "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse(_body("VALIDATION_ERROR", "Invalid input", {"fields": fields}), status_code=422)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        rid = getattr(request.state, "request_id", None)
        log.error("unhandled %s (request_id=%s)", type(exc).__name__, rid)
        return JSONResponse(_body("INTERNAL", "Something went wrong", request_id=rid), status_code=500)
