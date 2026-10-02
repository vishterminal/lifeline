"""'Enter judge demo' works even when live Google/Twilio keys are configured."""
from app.config import get_settings


def test_judge_account_uses_sample_sources_even_with_live_keys(client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "connector_mode", "live")
    monkeypatch.setattr(s, "google_client_id", "live-client-id")
    monkeypatch.setattr(s, "google_client_secret", "live-secret")
    assert s.gmail_live  # the server itself is in live mode

    r = client.post("/api/auth/demo")
    assert r.status_code == 201 and r.json()["user"]["is_demo"] is True
    h = {"Authorization": f"Bearer {r.json()['token']}"}

    # A second click is a different, private account (judges never collide)
    other = client.post("/api/auth/demo").json()["user"]
    assert other["email"] != r.json()["user"]["email"]

    gm = [x for x in client.get("/api/sources", headers=h).json() if x["kind"] == "GMAIL"][0]
    assert gm["mode"] == "mock"
    url = client.get("/api/sources/gmail/connect", headers=h).json()["auth_url"]
    assert url.startswith("/api/sources/gmail/callback")  # sample inbox, not Google
    client.get(url, follow_redirects=False)
    sync = client.post("/api/sources/gmail/sync", headers=h).json()
    assert sync["fetched"] >= 6 and sync["flagged"] == 1


def test_real_account_still_goes_to_google_with_live_keys(client, db, monkeypatch):
    """Real accounts (created by Google sign-in, is_demo=False) keep using live Gmail."""
    from app.models import User
    from app.security import create_jwt, hash_password

    s = get_settings()
    monkeypatch.setattr(s, "connector_mode", "live")
    monkeypatch.setattr(s, "google_client_id", "live-client-id")
    monkeypatch.setattr(s, "google_client_secret", "live-secret")
    u = User(email="real.person@gmail.com", password_hash=hash_password("x" * 12), google_sub="g-123", is_demo=False)
    db.add(u); db.commit()
    h = {"Authorization": f"Bearer {create_jwt(u.id)}"}
    url = client.get("/api/sources/gmail/connect", headers=h).json()["auth_url"]
    assert url.startswith("https://accounts.google.com/") and "gmail.readonly" in url


def test_email_signup_is_a_real_account(client, db, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "connector_mode", "live")
    monkeypatch.setattr(s, "google_client_id", "live-client-id")
    monkeypatch.setattr(s, "google_client_secret", "live-secret")
    r = client.post("/api/auth/register", json={"email": "real.user@example.com", "password": "password123", "name": "Real"})
    assert r.json()["user"]["is_demo"] is False
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    url = client.get("/api/sources/gmail/connect", headers=h).json()["auth_url"]
    assert url.startswith("https://accounts.google.com/") and "gmail.readonly" in url  # their own inbox


def test_old_demo_signups_become_real_at_sign_in(client, db):
    from app.models import User
    from app.security import hash_password

    db.add(User(email="was.judge@example.com", password_hash=hash_password("password123"), is_demo=True))
    db.commit()
    r = client.post("/api/auth/login", json={"email": "was.judge@example.com", "password": "password123"})
    assert r.json()["user"]["is_demo"] is False


def test_cron_tick_needs_the_secret(client, monkeypatch):
    s = get_settings()
    assert client.get("/api/cron/tick").status_code == 401  # no secret configured: closed
    monkeypatch.setattr(s, "cron_secret", "cron-secret-123")
    assert client.get("/api/cron/tick", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/cron/tick", headers={"Authorization": "Bearer cron-secret-123"}).json() == {"status": "ok"}


def test_typed_bill_goes_to_review(client, user):
    h, _ = user
    r = client.post("/api/ingest/manual", json={"biller": "BESCOM", "type": "ELECTRICITY", "amount": 1250,
                                                 "due_date": "2030-10-20", "review": True}, headers=h).json()
    assert r["outcome"] == "NEEDS_CONFIRMATION"
    conf = [c for c in client.get("/api/confirmations", headers=h).json() if c["id"] == r["confirmation_id"]][0]
    assert conf["reason"] == "MANUAL_ENTRY" and conf["draft"]["fields"]["amount"] == "1250"
    done = client.post(f"/api/confirmations/{conf['id']}/resolve", json={"action": "confirm"}, headers=h).json()
    assert done["outcome"] == "SAVED"
