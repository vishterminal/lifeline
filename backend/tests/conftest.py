from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="lifeline-test-"))
os.environ.update({
    "DATABASE_URL": f"sqlite:///{(_TMP / 'test.db').as_posix()}",
    "ENABLE_SCHEDULER": "false",
    "CONNECTOR_MODE": "mock",
    "LLM_MODE": "mock",
    "JWT_SECRET": "test-secret-that-is-long-enough-for-hs256-0123456789",
    "RATE_LIMIT_AUTH": "1000/minute",
    "RATE_LIMIT_INGEST": "1000/minute",
    "PUBLIC_BASE_URL": "https://lifeline.test",
    # Tests never use the developer's real keys from .env.
    "TWILIO_AUTH_TOKEN": "",
    "TWILIO_ACCOUNT_SID": "",
    "GOOGLE_CLIENT_ID": "",
    "GOOGLE_CLIENT_SECRET": "",
    "VAPID_PUBLIC_KEY": "",
    "VAPID_PRIVATE_KEY": "",
    "ANTHROPIC_API_KEY": "",
})
from cryptography.fernet import Fernet  # noqa: E402

os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402

DB_PATH = _TMP / "test.db"


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db(client):  # client startup creates tables + reference seeds
    s = SessionLocal()
    yield s
    s.close()


_counter = {"n": 0}


@pytest.fixture
def user(client):
    """Fresh user per test -> isolated data. Returns (headers, user_json)."""
    _counter["n"] += 1
    email = f"user{_counter['n']}@example.com"
    r = client.post("/api/auth/register", json={"email": email, "password": "password123", "name": "Ravi"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["user"]


@pytest.fixture
def settings():
    return get_settings()
