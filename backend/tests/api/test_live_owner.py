"""Owner accounts (LIVE_ACCOUNT_EMAILS) get real Gmail; everyone else stays in demo mode.
Only the owner's own mailbox can be connected."""
import secrets
from urllib.parse import parse_qs, urlparse

import pytest

from app.config import get_settings
from app.services import gmail_service


class _Resp:
    def __init__(self, status, data):
        self.status_code, self._data, self.text = status, data, str(data)

    def json(self):
        return self._data


@pytest.fixture
def live(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "connector_mode", "live")
    monkeypatch.setattr(s, "google_client_id", "cid")
    monkeypatch.setattr(s, "google_client_secret", "secret")
    monkeypatch.setattr(s, "live_account_emails", "Owner.Real@gmail.com, judge.real@gmail.com")
    return s


def _owner(live, name):
    """A fresh owner email for this test, added to the live list."""
    email = f"{name}.{secrets.token_hex(3)}@gmail.com"
    live.live_account_emails += "," + email
    return email


def _register(client, email):
    r = client.post("/api/auth/register", json={"email": email, "password": "password123", "name": "X"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["user"]


def _fake_google(monkeypatch, address):
    revoked = []

    def post(url, data=None, params=None, timeout=None):
        if url == gmail_service.REVOKE_URL:
            revoked.append(params)
            return _Resp(200, {})
        return _Resp(200, {"access_token": "at", "refresh_token": "rt", "scope": gmail_service.SCOPE})

    monkeypatch.setattr(gmail_service.httpx, "post", post)
    monkeypatch.setattr(gmail_service.httpx, "get", lambda url, headers=None, timeout=None: _Resp(200, {"emailAddress": address}))
    return revoked


def _connect(client, h):
    url = client.get("/api/sources/gmail/connect", headers=h).json()["auth_url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    return url, client.get(f"/api/sources/gmail/callback?code=abc&state={state}", follow_redirects=False)


def test_owner_email_is_a_live_account_everyone_else_demo(client, live):
    _, owner = _register(client, _owner(live, "owner"))
    _, other = _register(client, f"someone.{secrets.token_hex(3)}@gmail.com")
    assert owner["is_demo"] is False and other["is_demo"] is True


def test_owner_connects_real_gmail_others_get_sample_inbox(client, live, monkeypatch):
    judge = _owner(live, "judge")
    h, _ = _register(client, judge)
    url = client.get("/api/sources/gmail/connect", headers=h).json()["auth_url"]
    assert url.startswith(gmail_service.AUTH_URL) and "gmail.readonly" in url
    _fake_google(monkeypatch, judge.upper())  # Google may return different letter case
    _, r = _connect(client, h)
    assert r.status_code in (302, 307) and r.headers["location"].endswith("/connect?gmail=connected")
    gm = next(s for s in client.get("/api/sources", headers=h).json() if s["kind"] == "GMAIL")
    assert gm["mode"] == "live" and gm["status"] == "CONNECTED" and gm["gmail_address"] == judge.upper()

    hd, _ = _register(client, f"demo.{secrets.token_hex(3)}@gmail.com")
    assert "mock-code" in client.get("/api/sources/gmail/connect", headers=hd).json()["auth_url"]


def test_someone_elses_google_account_is_refused_and_revoked(client, live, monkeypatch):
    h, _ = _register(client, _owner(live, "owner"))
    revoked = _fake_google(monkeypatch, "stranger@gmail.com")
    _, r = _connect(client, h)
    assert r.headers["location"].endswith("/connect?gmail=wrong_account")
    assert revoked, "the stranger's token must be revoked"
    gm = next(s for s in client.get("/api/sources", headers=h).json() if s["kind"] == "GMAIL")
    assert gm["status"] == "ERROR" and gm["gmail_address"] is None


def test_owner_list_is_reapplied_at_sign_in(client, live, monkeypatch):
    _, u = _register(client, "later.judge@gmail.com")
    assert u["is_demo"] is True
    monkeypatch.setattr(live, "live_account_emails", "later.judge@gmail.com")
    r = client.post("/api/auth/login", json={"email": "later.judge@gmail.com", "password": "password123"})
    assert r.json()["user"]["is_demo"] is False
    monkeypatch.setattr(live, "live_account_emails", "")
    r = client.post("/api/auth/login", json={"email": "later.judge@gmail.com", "password": "password123"})
    assert r.json()["user"]["is_demo"] is True
