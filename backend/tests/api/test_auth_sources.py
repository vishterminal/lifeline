def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["connector_mode"] == "mock" and body["llm_mode"] == "mock"
    assert "missing_variables" in body


def test_register_login_me(client):
    r = client.post("/api/auth/register", json={"email": "Dup@Example.com", "password": "password123"})
    assert r.status_code == 201
    assert client.post("/api/auth/register", json={"email": "dup@example.com", "password": "password123"}).status_code == 409
    assert client.post("/api/auth/login", json={"email": "dup@example.com", "password": "nope-nope"}).status_code == 401
    tok = client.post("/api/auth/login", json={"email": "dup@example.com", "password": "password123"}).json()["token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert me.json()["user"]["email"] == "dup@example.com"
    assert client.get("/api/auth/me").status_code == 401


def test_validation_error_format(client):
    r = client.post("/api/auth/register", json={"email": "bad", "password": "short"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_profile_validation(client, user):
    h, _ = user
    assert client.put("/api/profile", json={"salary_day": 32}, headers=h).status_code == 422
    assert client.put("/api/profile", json={"phone_e164": "98765"}, headers=h).status_code == 422
    r = client.put("/api/profile", json={"salary_day": 1, "balance_amount": 25000, "phone_e164": "+919876500001"}, headers=h)
    assert r.status_code == 200 and r.json()["salary_day"] == 1 and r.json()["balance_as_of"]


def test_isolation(client, user):
    h1, _ = user
    r = client.post("/api/ingest/manual", json={"biller": "Acme Water", "type": "WATER", "amount": 300,
                                                 "due_date": "2030-01-10"}, headers=h1)
    oid = r.json()["obligation"]["id"]
    h2 = {"Authorization": "Bearer " + client.post("/api/auth/register", json={
        "email": "other-user@example.com", "password": "password123"}).json()["token"]}
    assert client.get(f"/api/obligations/{oid}", headers=h2).status_code == 404
    assert client.get("/api/obligations", headers=h2).json() == []


def test_sources_listing(client, user):
    h, _ = user
    kinds = {s["kind"]: s for s in client.get("/api/sources", headers=h).json()}
    assert set(kinds) == {"GMAIL", "SMS", "WHATSAPP"}
    assert kinds["SMS"]["webhook_url"].endswith("/api/ingest/sms") and kinds["SMS"]["checklist"]


def test_gmail_mock_connect_sync_disconnect(client, user):
    h, _ = user
    url = client.get("/api/sources/gmail/connect", headers=h).json()["auth_url"]
    assert "state=" in url
    path = url.split("lifeline.test", 1)[1]
    r = client.get(path, follow_redirects=False)
    assert r.status_code in (302, 307) and "gmail=connected" in r.headers["location"]
    # state is single-use
    assert client.get(path, follow_redirects=False).status_code == 403
    res = client.post("/api/sources/gmail/sync", headers=h).json()
    assert res["fetched"] >= 3 and res["flagged"] == 0  # fake mail isn't in the mock inbox
    again = client.post("/api/sources/gmail/sync", headers=h).json()
    assert again["fetched"] == 0  # cursor advanced
    assert client.delete("/api/sources/gmail", headers=h).json()["status"] == "DISCONNECTED"


def test_gmail_bad_state_rejected(client):
    assert client.get("/api/sources/gmail/callback?code=x&state=forged", follow_redirects=False).status_code == 403


def test_gmail_expired_token_needs_reconnect(client, user, monkeypatch):
    from app.services import gmail_service

    h, _ = user
    url = client.get("/api/sources/gmail/connect", headers=h).json()["auth_url"]
    client.get(url.split("lifeline.test", 1)[1], follow_redirects=False)

    def boom(src):
        raise gmail_service.NeedsReconnect("invalid_grant")

    monkeypatch.setattr(gmail_service, "fetch_mock", boom)
    assert client.post("/api/sources/gmail/sync", headers=h).json()["status"] == "NEEDS_RECONNECT"
    gm = [s for s in client.get("/api/sources", headers=h).json() if s["kind"] == "GMAIL"][0]
    assert gm["status"] == "NEEDS_RECONNECT" and "reconnect" in gm["last_error"]


def test_gmail_parse_message_extracts_headers_body_links():
    import base64

    from app.services.gmail_service import parse_message

    enc = lambda s: base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")  # noqa: E731
    msg = {"id": "m1", "internalDate": "1700000000000", "payload": {
        "headers": [{"name": "From", "value": "Netflix <info@mailer.netflix.com>"},
                    {"name": "Subject", "value": "Receipt"},
                    {"name": "Authentication-Results", "value": "dkim=pass; spf=pass; dmarc=pass"}],
        "mimeType": "multipart/alternative",
        "parts": [{"mimeType": "text/html", "body": {"data": enc('<p>Paid Rs 649</p><a href="https://netflix.com/x">netflix.com</a>')}}]}}
    m = parse_message(msg)
    assert m.sender == "info@mailer.netflix.com" and m.sender_name == "Netflix"
    assert "Paid Rs 649" in m.body and m.links == [("https://netflix.com/x", "netflix.com")]
    assert "dkim=pass" in m.auth_results
