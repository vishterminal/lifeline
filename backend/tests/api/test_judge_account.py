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


def test_real_account_still_goes_to_google_with_live_keys(client, user, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "connector_mode", "live")
    monkeypatch.setattr(s, "google_client_id", "live-client-id")
    monkeypatch.setattr(s, "google_client_secret", "live-secret")
    h, _ = user
    url = client.get("/api/sources/gmail/connect", headers=h).json()["auth_url"]
    assert url.startswith("https://accounts.google.com/") and "gmail.readonly" in url
