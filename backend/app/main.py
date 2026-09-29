from __future__ import annotations

import logging
import uuid
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from fastapi.responses import FileResponse, JSONResponse

from app import errors
from app.config import get_settings
from app.db import init_db
from app.jobs import scheduler
from app.ratelimit import limiter
from app.routers import auth, bills, demo, features, google_login, ingest, insights, reminders, review, sources
from app.services import upload_service

# Logs carry ids, outcomes and hashes only — never message bodies or tokens.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="Lifeline API", version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter
errors.install(app)


@app.exception_handler(RateLimitExceeded)
async def _rate_limited(request: Request, exc: RateLimitExceeded):
    return JSONResponse({"error": {"code": "RATE_LIMITED", "message": "Too many requests", "details": {}}},
                        status_code=429)


app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted({get_settings().frontend_origin, "http://localhost:5173", "http://localhost:8000"}),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    request.state.request_id = rid
    response = await call_next(request)
    response.headers["x-request-id"] = rid
    return response


for r in (auth.router, google_login.router, sources.router, ingest.router, review.router, bills.router, reminders.router, insights.router, features.router, demo.router):
    app.include_router(r, prefix="/api")


@app.get("/api/health")
def health():
    s = get_settings()
    return {
        "status": "ok",
        "connector_mode": s.connector_mode,
        "llm_mode": s.llm_mode,
        "connectors": {
            "google_login": "live" if s.google_login_live else "mock",
            "gmail": "live" if s.gmail_live else "mock",
            "whatsapp": "live" if s.twilio_live else "mock",
            "llm": "live" if s.llm_live else "mock",
            "local_ocr": "available" if upload_service.ocr_available() else "unavailable",
        },
        "missing_variables": s.missing_variables(),
        # Judge mode = no Google/Twilio keys: every source runs on realistic sample data.
        "judge_mode": not (s.gmail_live or s.twilio_live or s.google_login_live),
    }


# --- Serve the built web app (frontend/dist) so one command + one URL is enough ------------
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    if full_path.startswith("api/"):
        return JSONResponse({"error": {"code": "NOT_FOUND", "message": "Not found", "details": {}}}, status_code=404)
    target = (DIST / full_path).resolve()
    if full_path and target.is_file() and DIST in target.parents:
        return FileResponse(target)
    index = DIST / "index.html"
    if index.is_file():
        return FileResponse(index)
    return JSONResponse({"message": "Web app not built. Run: cd frontend && npm install && npm run build"}, status_code=503)
