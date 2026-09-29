"""R-REDACT: mask sensitive numbers before any cloud AI call (spec F7).

The raw text is never persisted or logged; callers keep it in memory only.
Masks keep the last 4 characters for context, e.g. XXXXXXXXXXXX1234.
"""
from __future__ import annotations

import re

_PAN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
_UPI = re.compile(r"\b([A-Za-z0-9._-]{2,256})@([A-Za-z][A-Za-z0-9]{2,64})\b")
_EMAIL_TLD = re.compile(r"\.[a-z]{2,}$", re.I)
# Digit runs, optionally grouped by spaces/hyphens (cards: 4-4-4-4, Aadhaar: 4-4-4)
_DIGIT_RUN = re.compile(r"(?<![\w.])(?:\d[ -]?){8,18}\d(?![\w])")
_PHONE = re.compile(r"(?<!\d)(?:\+?91[ -]?)?[6-9]\d{9}(?!\d)")


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _mask(digits: str, label: str) -> str:
    return f"[{label}:{'X' * max(len(digits) - 4, 0)}{digits[-4:]}]"


def _digits(match_text: str) -> str:
    return re.sub(r"\D", "", match_text)


def _replace_run(m: re.Match) -> str:
    raw = m.group(0)
    trail = raw[len(raw.rstrip(" -")):]
    d = _digits(raw)
    if 13 <= len(d) <= 19 and _luhn_ok(d):
        return _mask(d, "CARD") + trail
    if len(d) == 12:
        return _mask(d, "ID12") + trail  # Aadhaar-like
    if len(d) == 10 and d[0] in "6789":
        return _mask(d, "PHONE") + trail
    if 9 <= len(d) <= 18:
        return _mask(d, "ACCT") + trail
    return raw


def redact(text: str) -> str:
    out = _PAN.sub(lambda m: f"[PAN:XXXXXX{m.group(0)[-4:]}]", text)

    def _upi(m: re.Match) -> str:
        user, handle = m.group(1), m.group(2)
        # Leave e-mail addresses (handle followed by a TLD) alone; they are not UPI IDs.
        after = m.string[m.end():m.end() + 5]
        if _EMAIL_TLD.match(after) or after.startswith("."):
            return m.group(0)
        return f"[UPI:XXXX{user[-2:]}]@{handle}"

    out = _UPI.sub(_upi, out)
    out = _PHONE.sub(lambda m: _mask(_digits(m.group(0))[-10:], "PHONE"), out)
    out = _DIGIT_RUN.sub(_replace_run, out)
    return out
