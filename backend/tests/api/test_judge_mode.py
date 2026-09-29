"""The full judge demo: every channel, cross-channel merge, reset."""


def test_judge_demo_end_to_end(client, user):
    h, _ = user
    assert client.get("/api/health").json()["judge_mode"] is True
    fx = client.get("/api/demo/fixtures").json()
    assert all("[mock:" not in s["text"] for s in fx["sms"])  # test markers never shown to judges
    assert len(client.get("/api/demo/inbox", headers=h).json()) >= 6

    # Gmail sample inbox
    url = client.get("/api/sources/gmail/connect", headers=h).json()["auth_url"]
    client.get(url.split("lifeline.test", 1)[1], follow_redirects=False)
    sync = client.post("/api/sources/gmail/sync", headers=h).json()
    assert sync["flagged"] == 1 and sync["needs_review"] >= 3

    # Same TNEB bill again via WhatsApp and SMS -> still ONE review item listing all three channels
    wa = client.post("/api/demo/simulate/whatsapp", json={"fixture": "bill"}, headers=h).json()
    assert wa["phone_e164"].startswith("+9199") and wa["reply"]
    client.post("/api/demo/simulate/sms", json={"fixture": "bill"}, headers=h)
    confs = client.get("/api/confirmations", headers=h).json()
    tneb = [c for c in confs if c["draft"]["fields"]["biller_norm"] == "tneb"]
    assert len(tneb) == 1 and set(tneb[0]["draft"]["sources"]) == {"GMAIL", "WHATSAPP", "SMS"}

    r = client.post(f"/api/confirmations/{tneb[0]['id']}/resolve", json={"action": "confirm"}, headers=h).json()
    obl = client.get(f"/api/obligations/{r['obligation_id']}", headers=h).json()
    assert set(obl["source_kinds"]) == {"GMAIL", "WHATSAPP", "SMS"} and obl["origin"] == "DEMO"

    # Payment SMS closes it
    assert client.post("/api/demo/simulate/sms", json={"fixture": "debit"}, headers=h).json()["outcome"] == "PAID_DETECTED"

    # Reset wipes demo data and lets the whole demo run again
    client.delete("/api/demo", headers=h)
    assert client.get("/api/obligations", headers=h).json() == []
    assert client.get("/api/confirmations", headers=h).json() == []
    assert client.post("/api/demo/simulate/sms", json={"fixture": "bill"}, headers=h).json()["outcome"] != "DUPLICATE"


def test_web_app_served_or_clear_message(client):
    r = client.get("/connect")
    assert r.status_code in (200, 503)
    assert client.get("/api/nope").status_code == 404
