from datetime import date
from decimal import Decimal

import pytest

from app.services.extraction import rule_extractor
from app.services.extraction.reconcile import reconcile
from app.services.extraction.types import Extraction

TODAY = date(2026, 9, 29)


@pytest.mark.parametrize("text", ["Bill ₹1,840 due", "Bill Rs. 1840.00 due", "Bill INR 1840 due"])
def test_amount_formats(text):
    assert rule_extractor.extract(text + " on 30 Sep", [], TODAY).amount == Decimal("1840.00")


def test_amount_prefers_bill_over_late_fee():
    t = "Late fee Rs. 50 applies. Your bill of Rs. 1,840 is due on 30 Sep."
    assert rule_extractor.extract(t, [], TODAY).amount == Decimal("1840.00")


@pytest.mark.parametrize("text,expected,inferred", [
    ("due on 30 Sep", date(2026, 9, 30), True),
    ("due on 30/09/2026", date(2026, 9, 30), False),
    ("due on 30-Sep-26", date(2026, 9, 30), False),
    ("due on 2026-10-05", date(2026, 10, 5), False),
])
def test_date_formats(text, expected, inferred):
    e = rule_extractor.extract(f"Electricity bill Rs 100 {text}", [], TODAY)
    assert e.due_date == expected and e.date_year_inferred is inferred


def test_missing_year_prefers_future_for_dues():
    e = rule_extractor.extract("Bill Rs 100 due on 5 Jan", [], TODAY)
    assert e.due_date == date(2027, 1, 5)


def test_kinds_and_types(db):
    from app.services.billers import all_aliases

    aliases = all_aliases(db)
    e = rule_extractor.extract("Rs.1840.00 debited from A/c XX1234 to TNEB on 29 Sep", aliases, TODAY)
    assert e.message_kind == "PAYMENT_CONFIRMATION" and e.biller.startswith("TNEB")
    e = rule_extractor.extract("Your PUC certificate for TN09AB1234 expires on 4 Oct", aliases, TODAY)
    assert e.message_kind == "RENEWAL_NOTICE" and e.obligation_type == "PUC" and e.vehicle_ref == "TN09AB1234"
    e = rule_extractor.extract("Payment received Rs 649 on 21 Sep for Netflix", aliases, TODAY)
    assert e.message_kind == "RECEIPT" and e.obligation_type == "SUBSCRIPTION" and e.due_date == date(2026, 9, 21)


def _ex(**kw):
    base = dict(is_bill=True, message_kind="DUE_NOTICE", biller="TNEB", amount=Decimal("1840"),
                due_date=date(2026, 9, 30), confidence=0.8)
    base.update(kw)
    return Extraction(**base)


def test_reconcile_agree():
    r = reconcile(_ex(), _ex(confidence=0.7), "tneb", "tneb")
    assert r.agreed and r.reason is None and r.confidence >= 0.8


def test_reconcile_amount_mismatch():
    r = reconcile(_ex(amount=Decimal("1480")), _ex(), "tneb", "tneb")
    assert r.reason == "EXTRACTION_MISMATCH" and "amount" in r.mismatches
    assert r.candidates["llm"]["amount"] == "1480.00" and r.candidates["rules"]["amount"] == "1840.00"


def test_reconcile_date_mismatch():
    r = reconcile(_ex(due_date=date(2026, 10, 3)), _ex(), "tneb", "tneb")
    assert r.reason == "EXTRACTION_MISMATCH" and "due_date" in r.mismatches


def test_reconcile_llm_failure_rules_only():
    r = reconcile(None, _ex(), None, "tneb", "timeout")
    assert r.reason == "LOW_CONFIDENCE" and r.confidence <= 0.5 and r.candidates["llm_failure"] == "timeout"
