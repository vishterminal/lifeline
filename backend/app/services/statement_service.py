"""Bank-statement upload (spec F5): rows -> charge_events -> recurring detection.

CSV is the supported format; PDF is best-effort line parsing. Only merchant,
amount and date are kept — never the raw statement.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date
from decimal import Decimal, InvalidOperation

import dateparser
from sqlalchemy.orm import Session

from app.models import ChargeEvent, User
from app.services import billers, recurring_service
from app.services.redaction_service import redact

_DATE_KEYS = ("date", "txn date", "transaction date", "value date", "posting date")
_DESC_KEYS = ("description", "narration", "particulars", "details", "remarks", "merchant")
_DEBIT_KEYS = ("debit", "withdrawal", "withdrawal amt", "withdrawal amount", "dr", "debit amount")
_AMOUNT_KEYS = ("amount", "amt", "transaction amount")
_TYPE_KEYS = ("type", "dr/cr", "cr/dr")
_NOISE = re.compile(r"\b(upi|pos|ach|nach|ecs|imps|neft|debit card|dc|cc|si|autopay|txn|ref|[0-9/:-]{4,})\b", re.I)


def _find(headers: dict[str, str], keys) -> str | None:
    for k in keys:
        if k in headers:
            return headers[k]
    return None


def _money(v) -> Decimal | None:
    if v in (None, ""):
        return None
    s = re.sub(r"[^\d.\-]", "", str(v))
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    return d.quantize(Decimal("0.01"))


def _date(v) -> date | None:
    if not v:
        return None
    dt = dateparser.parse(str(v), languages=["en"], settings={"DATE_ORDER": "DMY"})
    return dt.date() if dt else None


def merchant_of(description: str, aliases) -> tuple[str, str]:
    hit = billers.find_in_text(description, aliases)
    if hit:
        return hit.canonical_name, hit.display_name
    cleaned = _NOISE.sub(" ", redact(description))
    cleaned = re.sub(r"\[[A-Z0-9]+:[X0-9]+\]", " ", cleaned)
    words = [w for w in re.split(r"[^A-Za-z&]+", cleaned) if len(w) > 1][:3]
    name = " ".join(words) or "unknown"
    return billers.slugify(name), name.title()


def parse_csv(data: bytes) -> list[tuple[date, str, Decimal]]:
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for raw in reader:
        headers = {(k or "").strip().lower(): (k or "") for k in raw.keys()}
        get = lambda keys: raw.get(_find(headers, keys) or "", None)  # noqa: E731
        d = _date(get(_DATE_KEYS))
        desc = (get(_DESC_KEYS) or "").strip()
        amt = _money(get(_DEBIT_KEYS))
        if amt is None:
            amt = _money(get(_AMOUNT_KEYS))
            typ = (get(_TYPE_KEYS) or "").strip().lower()
            if amt is not None and typ in ("cr", "credit"):
                continue
            if amt is not None and amt < 0:
                amt = -amt
            elif amt is not None and typ not in ("dr", "debit", ""):
                continue
        if d and desc and amt and amt > 0:
            rows.append((d, desc, amt))
    return rows


_PDF_LINE = re.compile(r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2} \w{3} \d{2,4})\s+(.+?)\s+([\d,]+\.\d{2})")


def parse_pdf(data: bytes) -> list[tuple[date, str, Decimal]]:
    from app.services.upload_service import pdf_text

    rows = []
    for line in pdf_text(data, max_pages=30).splitlines():
        m = _PDF_LINE.search(line)
        if m and not re.search(r"\bcr\b|credit|salary|refund", line, re.I):
            d, amt = _date(m.group(1)), _money(m.group(3))
            if d and amt:
                rows.append((d, m.group(2), amt))
    return rows


def import_statement(db: Session, user: User, data: bytes, filename: str | None,
                     current_balance: Decimal | None = None, origin: str = "REAL") -> dict:
    is_pdf = data[:5] == b"%PDF-" or (filename or "").lower().endswith(".pdf")
    rows = parse_pdf(data) if is_pdf else parse_csv(data)
    aliases = billers.all_aliases(db)
    merchants: dict[str, str] = {}
    added = 0
    for d, desc, amt in rows:
        norm, display = merchant_of(desc, aliases)
        exists = db.query(ChargeEvent.id).filter_by(user_id=user.id, merchant_norm=norm, charge_date=d, amount=amt).first()
        if exists:
            continue
        db.add(ChargeEvent(user_id=user.id, origin=origin, charge_date=d, merchant_norm=norm, amount=amt, source="STATEMENT"))
        merchants[norm] = display
        added += 1
    db.flush()
    recurring = []
    for norm, display in merchants.items():
        alias = next((a for a in aliases if a.canonical_name == norm), None)
        otype = alias.default_type if alias else "SUBSCRIPTION"
        sub = recurring_service.update_recurring(db, user.id, norm, display, otype, origin, "STATEMENT")
        if sub:
            recurring.append({"obligation_id": sub.id, "biller": display, "amount": str(sub.amount),
                              "next_expected_date": sub.next_expected_date.isoformat(),
                              "interval_days": sub.recurrence_interval_days, "price_changed": sub.price_changed})
    if current_balance is not None:
        from app.timeutil import now_utc

        user.balance_amount = current_balance
        user.balance_as_of = now_utc()
    return {"rows_parsed": len(rows), "charges_found": added, "recurring_found": len(recurring), "recurring": recurring}
