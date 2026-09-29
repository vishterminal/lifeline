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
    # Without Google keys, each sign-in is a private judge demo account (judges never collide)
    assert me["email"].startswith("judge-") and me["is_demo"] is True
    r = client.get("/api/auth/google/start", follow_redirects=False)
    loc2 = client.get(r.headers["location"], follow_redirects=False).headers["location"]
    tok2 = parse_qs(urlparse(loc2).fragment)["token"][0]
    me2 = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok2}"}).json()["user"]
    assert me2["email"] != me["email"]


def test_google_callback_rejects_forged_state(client):
    client.cookies.clear()
    r = client.get("/api/auth/google/callback?code=x&state=forged", follow_redirects=False)
    assert r.status_code == 302 and "error=state_mismatch" in r.headers["location"]
