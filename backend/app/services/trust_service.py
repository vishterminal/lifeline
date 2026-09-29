"""R-TRUST: fake-mail / sender trust scoring (spec F9, Section 13).

Risk 0-100, higher = riskier. Reduces risk; cannot eliminate it.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from functools import lru_cache
from urllib.parse import urlparse

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import DATA_DIR
from app.models import BillerAlias, ChargeEvent, Obligation


@lru_cache
def _cfg() -> dict:
    return yaml.safe_load((DATA_DIR / "trust_config.yaml").read_text(encoding="utf-8"))


@dataclass
class TrustInput:
    source_kind: str  # GMAIL | SMS | WHATSAPP | UPLOAD | MANUAL
    sender: str | None = None  # email address or SMS header
    auth_results: str | None = None  # raw Authentication-Results header
    links: list[tuple[str, str]] = field(default_factory=list)  # (href, anchor text)
    text: str = ""  # redacted text
    alias: BillerAlias | None = None  # claimed biller
    biller_norm: str | None = None
    amount: Decimal | None = None
    event_date: date | None = None
    message_kind: str | None = None


@dataclass
class TrustResult:
    score: int
    label: str
    reasons: list[str]
    has_history: bool
    force_confirm: bool = False  # red flag that history must never offset (personal mailbox)

    @property
    def suspicious(self) -> bool:
        return self.label == "SUSPICIOUS"

    @property
    def needs_confirmation(self) -> bool:
        return self.force_confirm or self.label in ("NEW_BILLER_CONFIRM",) or (
            _cfg()["thresholds"]["verified_max"] < self.score <= _cfg()["thresholds"]["confirm_max"]
        )


def levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def email_domain(sender: str | None) -> str | None:
    if not sender:
        return None
    m = re.search(r"@([A-Za-z0-9.-]+)", sender)
    return m.group(1).lower().rstrip(".") if m else None


def _domain_matches(domain: str, official: list[str]) -> bool:
    return any(domain == o.lower() or domain.endswith("." + o.lower()) for o in official)


def _brand(official_domain: str) -> str:
    return official_domain.lower().split(".")[-2] if "." in official_domain else official_domain.lower()


def is_lookalike(domain: str, aliases: list[BillerAlias]) -> BillerAlias | None:
    """Domain that imitates an official one without being it (netf1ix-billing.co)."""
    maxd = _cfg()["lookalike_max_distance"]
    tokens = [t for t in re.split(r"[.\-_]", domain) if t]
    for a in aliases:
        if not a.official_domains or _domain_matches(domain, a.official_domains):
            continue
        for od in a.official_domains:
            brand = _brand(od)
            if len(brand) < 4:
                continue
            if any(levenshtein(t, brand) <= maxd for t in tokens) or levenshtein(domain, od.lower()) <= maxd:
                return a
    return None


def parse_auth_results(header: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not header:
        return out
    for mech in ("spf", "dkim", "dmarc"):
        m = re.search(rf"\b{mech}=(\w+)", header, re.I)
        if m:
            out[mech] = m.group(1).lower()
    return out


def _host(url_or_text: str) -> str | None:
    s = url_or_text.strip()
    if not s:
        return None
    if "://" not in s:
        if " " in s or "." not in s:
            return None
        s = "http://" + s
    host = urlparse(s).hostname
    return host.lower().removeprefix("www.") if host else None


def _is_own_address(db: Session, user_id: str, sender: str | None) -> bool:
    """A bill you forwarded to yourself comes from your own mailbox — that's you, not a stranger."""
    from app.models import ConnectedSource, User

    if not sender:
        return False
    addr = sender.strip().lower()
    user = db.get(User, user_id)
    src = db.scalar(select(ConnectedSource).where(ConnectedSource.user_id == user_id, ConnectedSource.kind == "GMAIL"))
    own = {a.lower() for a in (user.email if user else None, src.gmail_address if src else None) if a}
    return addr in own


def _history(db: Session, user_id: str, biller_norm: str | None, exclude_origin_demo: bool = False):
    if not biller_norm:
        return [], []
    obls = list(db.scalars(select(Obligation).where(
        Obligation.user_id == user_id, Obligation.biller_norm == biller_norm)))
    charges = list(db.scalars(select(ChargeEvent).where(
        ChargeEvent.user_id == user_id, ChargeEvent.merchant_norm == biller_norm)))
    return obls, charges


def score(db: Session, user_id: str, t: TrustInput, aliases: list[BillerAlias]) -> TrustResult:
    w = _cfg()["weights"]
    risk = 0
    reasons: list[str] = []
    alias = t.alias
    sender_verified = False
    force_confirm = False

    if t.source_kind == "GMAIL":
        domain = email_domain(t.sender)
        auth = parse_auth_results(t.auth_results)
        domain_ok = bool(domain and alias and alias.official_domains and _domain_matches(domain, alias.official_domains))
        if domain and alias and alias.official_domains and not domain_ok:
            risk += w["domain_not_official"]
            reasons.append(f"Sender domain {domain} is not an official {alias.display_name} domain")
        if domain in set(_cfg().get("personal_mailbox_domains") or []) and not _is_own_address(db, user_id, t.sender):
            risk += w["personal_mailbox_sender"]
            force_confirm = True
            reasons.append(f"Sent from a personal {domain} account — companies don't send bills from these")
        if domain:
            look = is_lookalike(domain, aliases)
            if look:
                risk += w["lookalike_domain"]
                reasons.append(f"Sender domain {domain} looks like {look.display_name}'s but is not")
        fails = {k: v for k, v in auth.items() if v in ("fail", "softfail", "permerror", "none")}
        for mech, key in (("dkim", "dkim_fail"), ("spf", "spf_fail"), ("dmarc", "dmarc_fail")):
            if mech in fails:
                risk += w[key]
                reasons.append(f"{mech.upper()} check failed")
        all_pass = all(auth.get(m) == "pass" for m in ("spf", "dkim", "dmarc"))
        if all_pass and domain_ok:
            risk += w["all_auth_pass_and_domain_match"]
            sender_verified = bool(alias and alias.reference_verified)
    elif t.source_kind == "SMS":
        from app.services.billers import by_sender_id

        sid_alias = by_sender_id(t.sender, aliases)
        sender_verified = bool(sid_alias and alias and sid_alias.id == alias.id and alias.reference_verified)

    # Links whose visible text names a different host than the real target.
    for href, anchor in t.links:
        h_href, h_text = _host(href), _host(anchor)
        if h_href and h_text and not (h_href == h_text or h_href.endswith("." + h_text)):
            risk += w["link_host_mismatch"]
            reasons.append(f"Link text shows {h_text} but points to {h_href}")
            break

    low = t.text.lower()
    if any(p in low for p in _cfg()["pressure_phrases"]):
        risk += w["pressure_words"]
        reasons.append("Uses pressure wording")

    if alias and (alias.behavior or {}).get("never_sends_payment_demand") and t.message_kind in ("DUE_NOTICE",):
        risk += w["behavior_violation"]
        reasons.append(f"{alias.display_name} auto-charges and does not send payment demands")

    # Cross-check with the user's own data.
    obls, charges = _history(db, user_id, t.biller_norm)
    has_history = bool(obls or charges)
    if t.biller_norm and not has_history:
        risk += w["no_history"]
        reasons.append("No history with this biller yet")
    if has_history and t.amount is not None:
        past = [o.amount for o in obls if o.amount] + [c.amount for c in charges]
        if past:
            typical = Decimal(str(statistics.median(past)))
            if typical > 0 and abs(t.amount - typical) / typical * 100 > _cfg()["amount_deviation_pct"]:
                risk += w["amount_deviation"]
                reasons.append(f"Amount differs from your usual ₹{typical:,.0f}")
        cycle = alias.billing_cycle_days if alias else None
        if cycle and t.event_date and cycle <= 90:
            dates = sorted([c.charge_date for c in charges] + [o.due_date for o in obls])
            prior = [d for d in dates if d < t.event_date - timedelta(days=3)]
            if prior:
                expected = prior[-1] + timedelta(days=cycle)
                if abs((t.event_date - expected).days) > _cfg()["timing_off_days"]:
                    risk += w["timing_off_cycle"]
                    reasons.append("Date is off your usual billing cycle")
        if t.amount is not None:
            recent = [c for c in charges if t.event_date is None or abs((t.event_date - c.charge_date).days) <= 45]
            if any(abs(c.amount - t.amount) <= t.amount * Decimal("0.02") for c in recent):
                risk += w["recent_matching_charge"]
                reasons.append("Matches a recent charge in your history")

    risk = max(0, min(100, risk))
    th = _cfg()["thresholds"]
    if risk > th["confirm_max"]:
        label = "SUSPICIOUS"
    elif t.biller_norm and not has_history:
        label = "NEW_BILLER_CONFIRM"
    elif risk <= th["verified_max"] and sender_verified:
        label = "VERIFIED_SENDER"
    elif t.source_kind in ("WHATSAPP", "UPLOAD", "MANUAL"):
        label = "NOT_APPLICABLE"  # no sender headers; cross-check only
    else:
        label = "UNVERIFIED"
    return TrustResult(risk, label, reasons, has_history, force_confirm)
