from datetime import date, timedelta

import pytest

from app.services.gmail_service import render_fixture_text


def _d(days):
    return (date.today() + timedelta(days=days)).strftime("%d %b %Y")


@pytest.fixture
def sms_token(client, user):
    h, _ = user
    tok = client.post("/api/sources/sms/token", headers=h).json()["token"]
    return h, tok


def _sms(client, tok, text, sender="VM-TNEBLT", as_form=False):
    body = {"sender": sender, "text": text, "received_at": "1759132800000"}
    if as_form:
        return client.post("/api/ingest/sms", data=body, headers={"X-Ingest-Token": tok})
    return client.post("/api/ingest/sms", json=body, headers={"X-Ingest-Token": tok})


def test_sms_bad_token(client):
    r = client.post("/api/ingest/sms", json={"text": "bill due"}, headers={"X-Ingest-Token": "abcd.wrong"})
    assert r.status_code == 401
    assert client.post("/api/ingest/sms", json={"text": "x"}).status_code == 401


def test_sms_otp_dropped_personal_dropped(client, sms_token):
    h, tok = sms_token
    assert _sms(client, tok, "Your OTP is 482913. Do not share it with anyone.").json() == {"status": "dropped"}
    assert _sms(client, tok, "Hey, dinner tonight?", sender="+919800000000").json() == {"status": "dropped"}
    events = client.get("/api/ingest-events", headers=h).json()
    otp = [e for e in events if e["outcome"] == "DROPPED_OTP"]
    assert otp


def test_sms_bill_confirm_then_timeline_and_duplicate(client, sms_token):
    h, tok = sms_token
    text = f"TNEB: Your electricity bill of Rs.1840.00 is due on {_d(1)}. Pay to avoid late fee."
    assert _sms(client, tok, text).json() == {"status": "accepted"}
    # First bill from a biller with no history -> confirmation (NEW_BILLER), not auto-saved.
    confs = client.get("/api/confirmations", headers=h).json()
    assert len(confs) == 1 and confs[0]["reason"] == "NEW_BILLER"
    f = confs[0]["draft"]["fields"]
    assert f["amount"] == "1840.00" and f["type"] == "ELECTRICITY" and f["due_date"] == (date.today() + timedelta(days=1)).isoformat()
    r = client.post(f"/api/confirmations/{confs[0]['id']}/resolve", json={"action": "confirm"}, headers=h)
    assert r.status_code == 200 and r.json()["outcome"] == "SAVED"
    obls = client.get("/api/obligations", headers=h).json()
    assert len(obls) == 1 and obls[0]["amount"] == "1840.00" and obls[0]["source_kinds"] == ["SMS"]
    # forwarder retry -> idempotent
    assert _sms(client, tok, text).json() == {"status": "accepted"}
    assert client.get("/api/ingest-events", headers=h).json()[0]["outcome"] == "DUPLICATE"
    # a second bill from the same (now known) biller is saved automatically
    text2 = f"TNEB: Your electricity bill of Rs.1790.00 is due on {_d(61)}. Pay to avoid late fee."
    _sms(client, tok, text2, as_form=True)
    assert len(client.get("/api/obligations", headers=h).json()) == 2


def test_sms_debit_marks_paid(client, sms_token):
    h, tok = sms_token
    client.post("/api/ingest/manual", json={"biller": "TNEB", "type": "ELECTRICITY", "amount": 1840,
                                             "due_date": (date.today() + timedelta(days=1)).isoformat()}, headers=h)
    _sms(client, tok, f"Rs.1840.00 debited from A/c XX1234 to TNEB on {_d(0)}. Avl bal Rs.20,150.00", sender="VM-HDFCBK")
    obls = client.get("/api/obligations", headers=h).json()
    assert obls[0]["status"] == "PAID" and obls[0]["paid_via"] == "AUTO_DETECTED"


def test_sms_unparseable_accepted_quietly(client, sms_token):
    _, tok = sms_token
    r = client.post("/api/ingest/sms", content=b"garbage", headers={"X-Ingest-Token": tok, "content-type": "text/plain"})
    assert r.status_code == 200 and r.json()["status"] == "dropped"


def test_sms_field_mapping_alternate_names(client, sms_token):
    h, tok = sms_token
    r = client.post("/api/ingest/sms", json={"from": "VM-AIRTEL", "message": f"Airtel postpaid bill Rs 799 due on {_d(9)}"},
                    headers={"X-Ingest-Token": tok})
    assert r.json()["status"] == "accepted"
    assert client.get("/api/confirmations", headers=h).json()


def test_token_rotation_invalidates_old(client, sms_token):
    h, old = sms_token
    new = client.post("/api/sources/sms/token", headers=h).json()["token"]
    assert _sms(client, old, "bill due").status_code == 401
    assert _sms(client, new, "Hey").status_code == 200


def test_mismatch_requires_user_choice(client, user):
    h, _ = user
    client.post("/api/demo/simulate/sms", json={"fixture": "mismatch"}, headers=h)
    conf = client.get("/api/confirmations", headers=h).json()[0]
    assert conf["reason"] == "EXTRACTION_MISMATCH"
    c = conf["draft"]["candidates"]
    assert c["llm"]["amount"] == "899.00" and c["rules"]["amount"] == "799.00"
    r = client.post(f"/api/confirmations/{conf['id']}/resolve", json={"action": "confirm"}, headers=h)
    assert r.status_code == 422 and r.json()["error"]["details"]["field"] == "amount"
    r = client.post(f"/api/confirmations/{conf['id']}/resolve", json={"action": "confirm", "fields": {"amount": 799}}, headers=h)
    assert r.status_code == 200
    assert client.get("/api/obligations", headers=h).json()[0]["amount"] == "799.00"


def test_llm_failure_degrades_to_confirmation(client, user):
    h, _ = user
    r = client.post("/api/demo/simulate/sms", json={"text": f"Jio bill Rs 399 due on {_d(4)} [mock:llm-fail]"}, headers=h).json()
    assert r["outcome"] == "NEEDS_CONFIRMATION" and r["reason"] == "LOW_CONFIDENCE"
    r = client.post("/api/demo/simulate/sms", json={"text": f"Jio bill Rs 499 due on {_d(5)} [mock:llm-invalid]"}, headers=h).json()
    assert r["outcome"] == "NEEDS_CONFIRMATION"


def test_fake_email_flagged_no_obligation(client, user):
    h, _ = user
    r = client.post("/api/demo/simulate/fake-email", headers=h).json()
    assert r["outcome"] == "SUSPICIOUS"
    assert client.get("/api/obligations", headers=h).json() == []
    flagged = client.get("/api/flagged", headers=h).json()
    assert flagged[0]["claimed_biller"] == "Netflix" and flagged[0]["risk_score"] > 60
    assert client.post(f"/api/flagged/{flagged[0]['id']}/dismiss", headers=h).status_code == 200
    assert client.get("/api/flagged", headers=h).json() == []


def test_injection_has_no_effect(client, user):
    h, _ = user
    client.post("/api/ingest/manual", json={"biller": "TNEB", "type": "ELECTRICITY", "amount": 1840,
                                             "due_date": (date.today() + timedelta(days=1)).isoformat()}, headers=h)
    r = client.post("/api/demo/simulate/email", json={"fixture": "_injection"}, headers=h).json()
    assert r["outcome"] in ("NEEDS_CONFIRMATION", "SAVED")
    statuses = {o["biller_norm"]: o["status"] for o in client.get("/api/obligations", headers=h).json()}
    assert statuses["tneb"] == "OPEN"


def test_same_bill_email_then_whatsapp_merges(client, user):
    h, _ = user
    client.put("/api/sources/whatsapp", json={"phone_e164": "+919811100001"}, headers=h)
    client.post("/api/ingest/manual", json={"biller": "TNEB", "type": "ELECTRICITY", "amount": 1500,
                                             "due_date": (date.today() - timedelta(days=58)).isoformat()}, headers=h)
    r1 = client.post("/api/demo/simulate/email", json={"fixture": "tneb_bill"}, headers=h).json()
    assert r1["outcome"] == "SAVED", r1
    r2 = client.post("/api/demo/simulate/whatsapp", json={"fixture": "bill"}, headers=h).json()
    assert "Already tracking" in r2["reply"]
    open_ = [o for o in client.get("/api/obligations?status=OPEN", headers=h).json() if o["biller_norm"] == "tneb"]
    assert len(open_) == 1 and set(open_[0]["source_kinds"]) == {"GMAIL", "WHATSAPP"}


def test_statement_csv_detects_recurring(client, user):
    h, _ = user
    d = lambda n: (date.today() - timedelta(days=n)).strftime("%d/%m/%Y")  # noqa: E731
    csv = ("Date,Narration,Withdrawal Amt,Deposit Amt\n"
           f"{d(68)},POS NETFLIX.COM MUMBAI,649.00,\n"
           f"{d(38)},POS NETFLIX.COM MUMBAI,649.00,\n"
           f"{d(8)},POS NETFLIX.COM MUMBAI,649.00,\n"
           f"{d(20)},UPI-SWIGGY-1234,350.00,\n"
           f"{d(5)},SALARY CREDIT,,85000.00\n")
    r = client.post("/api/ingest/statement", files={"file": ("stmt.csv", csv, "text/csv")},
                    data={"current_balance": "24500"}, headers=h).json()
    assert r["charges_found"] == 4 and r["recurring_found"] == 1
    sub = r["recurring"][0]
    assert sub["biller"] == "Netflix" and sub["interval_days"] == 30
    assert sub["next_expected_date"] == (date.today() + timedelta(days=22)).isoformat()
    assert client.get("/api/profile", headers=h).json()["balance_amount"] == "24500.00"
    # re-upload is idempotent
    r2 = client.post("/api/ingest/statement", files={"file": ("stmt.csv", csv, "text/csv")}, headers=h).json()
    assert r2["charges_found"] == 0


def test_receipt_email_after_statement_updates_subscription(client, user):
    h, _ = user
    d = lambda n: (date.today() - timedelta(days=n)).strftime("%d/%m/%Y")  # noqa: E731
    csv = f"Date,Narration,Debit\n{d(68)},NETFLIX,649\n{d(38)},NETFLIX,649\n"
    client.post("/api/ingest/statement", files={"file": ("s.csv", csv, "text/csv")}, headers=h)
    # Statement predicted a renewal ~8 days ago; the receipt for that charge marks it paid...
    r = client.post("/api/demo/simulate/email", json={"fixture": "netflix_receipt"}, headers=h).json()
    assert r["outcome"] == "PAID_DETECTED", r
    # ...and the next cycle is tracked automatically.
    open_ = client.get("/api/obligations?status=OPEN", headers=h).json()
    assert len(open_) == 1 and open_[0]["is_recurring"]
    assert open_[0]["next_expected_date"] == (date.today() + timedelta(days=22)).isoformat()
    assert set(open_[0]["source_kinds"]) >= {"GMAIL"}


def test_upload_limits_and_image_without_ocr(client, user):
    h, _ = user
    big = b"%PDF-" + b"0" * (10 * 1024 * 1024 + 10)
    assert client.post("/api/ingest/upload", files={"file": ("a.pdf", big, "application/pdf")}, headers=h).status_code == 413
    assert client.post("/api/ingest/upload", files={"file": ("a.txt", b"hello", "text/plain")}, headers=h).status_code == 415
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    r = client.post("/api/ingest/upload", files={"file": ("bill.png", png, "image/png")}, headers=h).json()
    assert r["outcome"] == "NEEDS_CONFIRMATION"


def _pdf_with_text(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 50 750 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


def test_pdf_upload_extracts(client, user):
    h, _ = user
    pdf = _pdf_with_text(f"BESCOM electricity bill Rs. 2,310.00 due on {_d(12)}")
    r = client.post("/api/ingest/upload", files={"file": ("bill.pdf", pdf, "application/pdf")}, headers=h).json()
    # user-supplied upload skips the new-biller confirmation
    assert r["outcome"] == "SAVED", r
    o = client.get(f"/api/obligations/{r['obligation_id']}", headers=h).json()
    assert o["amount"] == "2310.00" and o["type"] == "ELECTRICITY" and o["source_kinds"] == ["UPLOAD"]


def test_manual_entry_validation(client, user):
    h, _ = user
    assert client.post("/api/ingest/manual", json={"biller": "X", "type": "NOPE", "due_date": "2030-01-01"}, headers=h).status_code == 422
    r = client.post("/api/ingest/manual", json={"biller": "Netflix", "amount": 649, "due_date": "2030-01-01",
                                                 "recurring": "MONTHLY"}, headers=h)
    assert r.status_code == 201 and r.json()["obligation"]["type"] == "SUBSCRIPTION" and r.json()["obligation"]["is_recurring"]


def test_reject_confirmation(client, user):
    h, _ = user
    client.post("/api/demo/simulate/sms", json={"fixture": "insurance"}, headers=h)
    conf = client.get("/api/confirmations", headers=h).json()[0]
    assert client.post(f"/api/confirmations/{conf['id']}/resolve", json={"action": "reject"}, headers=h).json()["status"] == "REJECTED"
    assert client.get("/api/obligations", headers=h).json() == []
    assert client.post(f"/api/confirmations/{conf['id']}/resolve", json={"action": "reject"}, headers=h).status_code == 409


def test_fixture_date_rendering():
    assert render_fixture_text("{{date:+0}}") == date.today().strftime("%d %b %Y")
