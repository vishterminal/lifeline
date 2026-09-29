"""Vercel serverless entry point: the FastAPI backend as one Python function.

Vercel has no persistent disk, so the hosted demo keeps its SQLite file in /tmp
(judge mode only; it can reset after inactivity). The static web app is served by
Vercel from frontend/dist.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

# Shared Postgres when the project has one (Vercel Marketplace: Neon); otherwise a /tmp SQLite file.
if not os.environ.get("DATABASE_URL"):
    pg = os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL_UNPOOLED")
    if pg:
        os.environ["DATABASE_URL"] = pg
    else:
        os.environ["DATABASE_URL"] = "sqlite:////tmp/lifeline.db"
        os.environ.setdefault("EPHEMERAL_DB", "true")
os.environ.setdefault("ENABLE_SCHEDULER", "false")
os.environ.setdefault("CONNECTOR_MODE", "mock")
os.environ.setdefault("LLM_MODE", "mock")
os.environ.setdefault("RATE_LIMIT_AUTH", "120/minute")  # judges share proxy IPs

from app.db import init_db  # noqa: E402
from app.main import app  # noqa: E402,F401

init_db()  # serverless runtimes may skip ASGI lifespan events
