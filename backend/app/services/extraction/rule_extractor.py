"""Extractor B (RULE-1): regex + dateparser + alias table. No AI.

Deliberately independent of the LLM so that disagreements are meaningful.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

import dateparser

from app.models import BillerAlias
from app.services.billers import find_in_text
from app.services.extraction.types import Extraction

_AMOUNT = re.compile(r"(?:₹|\bRs\.?|\bINR|रु\.?|रुपये|ரூ\.?)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.I)
_AMOUNT_GOOD_CTX = re.compile(
    r"(bill|amount|due|payable|premium|charged|debited|received|paid|of|total|renew|price|fee for)\W*$", re.I
)
_AMOUNT_BAD_CTX = re.compile(r"(late fee|late payment|penalty|fine|balance|avl bal|available)\W*(of\W*)?$", re.I)

_MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
_DATE_PATTERNS = [
    re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b"),
    re.compile(r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b"),
    re.compile(rf"\b\d{{1,2}}(?:st|nd|rd|th)?[ -]{_MONTHS}\.?(?:[ ,-]+\d{{2,4}})?\b", re.I),
    re.compile(rf"\b{_MONTHS}\.? \d{{1,2}}(?:st|nd|rd|th)?(?:,? \d{{4}})?\b", re.I),
]
_YEAR_IN = re.compile(r"\d{4}|[/.-]\d{2}\b|[ ,-]\d{2}$")
_DUE_CTX = re.compile(r"(due|on or before|before|by|expires?|expiry|valid till|valid until|renew(?:al)?(?: date)?|last date)\W*(on|date|is)?\W*$", re.I)

_VEHICLE = re.compile(r"\b[A-Z]{2}[ -]?\d{1,2}[ -]?[A-Z]{1,3}[ -]?\d{4}\b")

_KIND_RULES: list[tuple[str, re.Pattern]] = [
    # "Rs.649 will be debited on 5 Oct (AutoPay)" announces a future charge: a renewal, not a payment.
    ("RENEWAL_NOTICE", re.compile(r"will be debited|to be debited|pre-?debit|scheduled debit", re.I)),
    ("PAYMENT_CONFIRMATION", re.compile(r"\bdebited\b|payment (?:was )?successful|paid successfully|has been paid|thank you for (?:your )?payment|payment of .* (?:is )?successful|transaction successful", re.I)),
    ("RECEIPT", re.compile(r"\breceipt\b|payment received|\bcharged\b|we(?:'ve| have) received your payment|invoice paid", re.I)),
    ("RENEWAL_NOTICE", re.compile(r"\brenew(?:al|ed|s)?\b|\bexpir(?:es|y|ing|ed)\b|valid (?:till|until)", re.I)),
    ("DUE_NOTICE", re.compile(r"\bdue\b|\bpay (?:by|before|now)\b|\bpayable\b|\bbill\b|\binvoice\b|\bemi\b"
                              r"|देय|बकाया|भुगतान करें|बिल|கட்டணம்|செலுத்த|நிலுவை|பில்", re.I)),
]

_TYPE_RULES: list[tuple[str, re.Pattern]] = [
    ("PUC", re.compile(r"\bpuc\b|pollution under control|pollution certificate", re.I)),
    ("INSURANCE_VEHICLE", re.compile(r"(bike|car|motor|vehicle|two[- ]wheeler).{0,30}insurance|insurance.{0,30}(bike|car|motor|vehicle|two[- ]wheeler)", re.I)),
    ("INSURANCE_OTHER", re.compile(r"insurance|policy premium|\bpremium\b", re.I)),
    ("DRIVING_LICENCE", re.compile(r"driving licen[cs]e|\bdl\b renewal", re.I)),
    ("LOAN_EMI", re.compile(r"\bemi\b|\bloan\b", re.I)),
    ("ELECTRICITY", re.compile(r"electricity|power bill|\bkwh\b|\beb bill\b|बिजली|மின்", re.I)),
    ("WATER", re.compile(r"\bwater (?:bill|charges|tax)\b", re.I)),
    ("GAS", re.compile(r"\b(?:lpg|gas) (?:bill|booking|cylinder)\b|piped gas", re.I)),
    ("PHONE_INTERNET", re.compile(r"broadband|postpaid|mobile bill|recharge|fiber|fibre|internet|पोस्टपेड|मोबाइल", re.I)),
    ("SUBSCRIPTION", re.compile(r"subscription|membership|\bplan\b.*(?:renew|charged)", re.I)),
    ("APPOINTMENT", re.compile(r"appointment", re.I)),
]


def _amounts(text: str) -> list[tuple[Decimal, int]]:
    """Return (amount, score) — higher score = more likely the bill amount."""
    found = []
    for m in _AMOUNT.finditer(text):
        try:
            val = Decimal(m.group(1).replace(",", ""))
        except InvalidOperation:
            continue
        if val <= 0:
            continue
        before = text[max(0, m.start() - 40):m.start()]
        score = 1
        if _AMOUNT_GOOD_CTX.search(before):
            score += 2
        if _AMOUNT_BAD_CTX.search(before):
            score -= 3
        found.append((val.quantize(Decimal("0.01")), score))
    return found


def _pick_amount(text: str) -> Decimal | None:
    cands = _amounts(text)
    if not cands:
        return None
    best = max(cands, key=lambda c: c[1])  # max keeps the first of equal scores
    return best[0] if best[1] > -1 else None


def _parse_date(raw: str, today: date, prefer: str) -> tuple[date | None, bool]:
    if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", raw):
        try:
            y, m, d = (int(p) for p in raw.split("-"))
            return date(y, m, d), False
        except ValueError:
            return None, False
    has_year = bool(_YEAR_IN.search(raw.strip()))
    settings = {
        "DATE_ORDER": "DMY",
        "PREFER_DAY_OF_MONTH": "first",
        "RELATIVE_BASE": datetime.combine(today, time()),
        "PREFER_DATES_FROM": prefer,
        "REQUIRE_PARTS": ["day", "month"],
    }
    try:
        dt = dateparser.parse(raw, languages=["en", "hi", "ta"], settings=settings)
    except Exception:  # dateparser can raise on odd inputs
        return None, False
    if dt is None:
        return None, False
    return dt.date(), not has_year


def _dates(text: str, today: date, prefer: str) -> list[tuple[date, bool, int]]:
    out: list[tuple[date, bool, int]] = []
    seen_spans: list[tuple[int, int]] = []
    for pat in _DATE_PATTERNS:
        for m in pat.finditer(text):
            if any(s <= m.start() < e for s, e in seen_spans):
                continue
            d, inferred = _parse_date(m.group(0), today, prefer)
            if d is None:
                continue
            seen_spans.append((m.start(), m.end()))
            score = 2 if _DUE_CTX.search(text[max(0, m.start() - 30):m.start()]) else 1
            out.append((d, inferred, score))
    return out


def detect_kind(text: str) -> str:
    for kind, pat in _KIND_RULES:
        if pat.search(text):
            return kind
    return "OTHER"


def detect_type(text: str, alias: BillerAlias | None) -> str:
    if alias is not None:
        return alias.default_type
    for t, pat in _TYPE_RULES:
        if pat.search(text):
            return t
    return "OTHER"


def extract(text: str, aliases: list[BillerAlias], today: date, sender_name: str | None = None) -> Extraction:
    kind = detect_kind(text)
    alias = find_in_text(text, aliases) or (find_in_text(sender_name, aliases) if sender_name else None)
    amount = _pick_amount(text)
    prefer = "past" if kind in ("PAYMENT_CONFIRMATION", "RECEIPT") else "future"
    dates = _dates(text, today, prefer)
    due, inferred = None, False
    if dates:
        d, inferred, _ = max(dates, key=lambda x: x[2])
        due = d
    vehicle = _VEHICLE.search(text)
    otype = detect_type(text, alias)

    recurrence = None
    if re.search(r"\bmonthly\b|per month|/month|/mo\b", text, re.I):
        recurrence = "MONTHLY"
    elif re.search(r"\bannual(?:ly)?\b|\byearly\b|per year|/year", text, re.I):
        recurrence = "ANNUAL"

    biller = alias.display_name if alias else (sender_name.strip() if sender_name else None)
    conf = 0.3 + (0.25 if amount else 0) + (0.25 if due else 0) + (0.2 if alias else 0)
    if inferred:
        conf -= 0.1
    is_bill = kind != "OTHER" and (amount is not None or due is not None)
    return Extraction(
        is_bill=is_bill,
        message_kind=kind,
        obligation_type=otype,
        biller=biller,
        amount=amount,
        currency="INR" if amount is not None else None,
        due_date=due,
        vehicle_ref=vehicle.group(0).replace(" ", "").replace("-", "") if vehicle else None,
        recurrence_hint=recurrence,
        date_year_inferred=inferred,
        confidence=round(max(0.0, min(conf, 0.95)), 2),
        notes="rules",
    )


def sanity_window(d: date | None, today: date) -> bool:
    """AI-1 validation window: -60 / +400 days of today."""
    return d is None or (today - timedelta(days=60)) <= d <= (today + timedelta(days=400))
