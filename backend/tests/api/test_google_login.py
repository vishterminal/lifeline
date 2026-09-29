from urllib.parse import parse_qs, urlparse


def test_mock_google_login_flow(client):
    r = client.get("/api/auth/google/start", follow_redirects=False)
    assert r.status_code == 302 and "lifeline_g_state" in r.headers.get("set-cookie", "")
    cb = r.headers["location"]
    r2 = client.get(cb, follow_redirects=False)
    loc = r2.headers["location"]
    assert "/auth/callback#token=" in loc
    frag = parse_qs(urlparse(loc).fragment)
    token = frag["token"][0]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["user"]
    assert me["email"] == "demo.google.user@gmail.com"
    # second sign-in -> same account, goes to inbox
    r = client.get("/api/auth/google/start", follow_redirects=False)
    loc2 = client.get(r.headers["location"], follow_redirects=False).headers["location"]
    assert "next=/inbox" in loc2


def test_google_callback_rejects_forged_state(client):
    client.cookies.clear()
    r = client.get("/api/auth/google/callback?code=x&state=forged", follow_redirects=False)
    assert r.status_code == 302 and "error=state_mismatch" in r.headers["location"]
