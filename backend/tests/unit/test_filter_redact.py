from app.services.filter_service import prefilter
from app.services.redaction_service import redact


def test_otp_dropped():
    r = prefilter("Your OTP is 482913. Do not share it with anyone.", "VM-HDFCBK", [])
    assert not r.keep and r.outcome == "DROPPED_OTP"


def test_do_not_share_with_code_is_otp():
    assert prefilter("Code 5521 for login. Do not share.", None, []).outcome == "DROPPED_OTP"


def test_bill_kept():
    assert prefilter("TNEB: Your electricity bill of Rs.1840.00 is due on 30 Sep.", "VM-TNEBLT", []).keep


def test_personal_dropped():
    r = prefilter("Hey, dinner tonight?", "+919800000000", [])
    assert not r.keep and r.outcome == "DROPPED_NOT_BILL"


def test_redacts_card_luhn_keeps_last4():
    out = redact("Card 4111 1111 1111 1111 was charged")
    assert "4111 1111 1111 1111" not in out and "1111]" in out and "CARD" in out


def test_redacts_aadhaar_pan_account_phone_upi():
    text = ("Aadhaar 2345 6789 0123, PAN ABCDE1234F, A/c 123456789012345, call 9876543210, "
            "pay ravi.kumar@okhdfc")
    out = redact(text)
    for raw in ("2345 6789 0123", "ABCDE1234F", "123456789012345", "9876543210", "ravi.kumar@"):
        assert raw not in out
    assert "0123]" in out and "234F]" in out and "2345]" in out and "3210]" in out and "@okhdfc" in out


def test_redaction_keeps_amounts_dates_and_emails():
    text = "Bill of Rs.1840.00 due on 30/09/2026 from billing@netflix.com"
    assert redact(text) == text
