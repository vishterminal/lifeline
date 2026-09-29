"""Consequence Engine (R-CONSEQ), Obligation Graph (R-GRAPH) and what-if (F15).

Pure calculation, no LLM. Penalty numbers come from penalty_rules_seed.json and are
labelled VERIFIED only when a real (non-placeholder) source is attached; the seed
ships placeholders, so everything shows ESTIMATED until the team adds sourced data.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from functools import lru_cache

from app.config import DATA_DIR
from app.models import Obligation

OPEN = ("OPEN", "OVERDUE")
VIRTUAL = {"VEHICLE_COMPLIANCE": "Vehicle compliance (checkpoint fine)"}
TYPE_LABEL = {
    "PUC": "PUC certificate", "INSURANCE_VEHICLE": "vehicle insurance", "DRIVING_LICENCE": "driving licence",
    "VEHICLE_COMPLIANCE": "vehicle compliance",
}
HIGH, MEDIUM = Decimal("5000"), Decimal("200")  # tiers (IMPLEMENTATION DECISION, spec F13)


class RuleError(ValueError):
    pass


@lru_cache
def penalty_rules() -> dict[str, dict]:
    rules = json.loads((DATA_DIR / "penalty_rules_seed.json").read_text(encoding="utf-8"))["rules"]
    out = {}
    for r in rules:
        src = (r.get("source_label") or "") + (r.get("source_url") or "")
        if r.get("verification") == "VERIFIED" and (not src.strip() or src.upper().startswith("PLACEHOLDER")):
            raise RuleError(f"{r['obligation_type']}: VERIFIED requires a real source_label or source_url")
        out[r["obligation_type"]] = r
    return out


@lru_cache
def dependency_rules() -> list[dict]:
    return json.loads((DATA_DIR / "dependency_rules_seed.json").read_text(encoding="utf-8"))["rules"]


def tier(total: Decimal) -> str:
    return "HIGH" if total >= HIGH else "MEDIUM" if total >= MEDIUM else "LOW"


def _d(v) -> Decimal:
    return Decimal(str(v or 0))


@dataclass
class Direct:
    amount: Decimal | None  # None = unknown
    verified: bool
    source: str | None
    why: str


def direct_cost(otype: str, bill_amount: Decimal | None, has_amount_source: bool = True) -> Direct:
    if otype == "SUBSCRIPTION":
        # No late fee exists: the consequence is the charge itself (spec F11).
        return Direct(bill_amount, bill_amount is not None, "Amount from your bill / receipt", "the renewal charge itself")
    r = penalty_rules().get(otype)
    if r is None:
        return Direct(None, False, None, "no penalty data for this kind of bill")
    ver = r.get("verification") == "VERIFIED"
    if r.get("lapse_cost"):
        return Direct(_d(r["lapse_cost"]), ver, r.get("source_label"), f"cost if it lapses (~₹{_d(r['lapse_cost']):,.0f})")
    fee = _d(r.get("late_fee_flat")) + (_d(r.get("late_fee_pct")) / 100) * (bill_amount or 0)
    return Direct(fee.quantize(Decimal("1")), ver, r.get("source_label"), f"late fee (~₹{fee:,.0f})")


def _same_vehicle(a: Obligation, b: Obligation, vehicles: set[str]) -> bool:
    if a.vehicle_ref and b.vehicle_ref:
        return a.vehicle_ref == b.vehicle_ref
    return len(vehicles) <= 1  # single-vehicle assumption (spec F12)


@dataclass
class Link:
    obligation_id: str | None
    label: str
    due_date: str | None
    relation: str
    explanation: str
    cost: Decimal | None
    weight: float


@dataclass
class Consequence:
    direct: Decimal | None
    downstream: Decimal
    total: Decimal
    label: str  # VERIFIED | ESTIMATED | UNKNOWN
    tier: str
    sources: list[str]
    explanation: list[str]
    upstream: list[Link] = field(default_factory=list)
    downstream_links: list[Link] = field(default_factory=list)
    chain_hint: str | None = None

    def as_dict(self) -> dict:
        def link(l: Link) -> dict:
            return {"obligation_id": l.obligation_id, "label": l.label, "due_date": l.due_date, "relation": l.relation,
                    "explanation": l.explanation, "cost": str(l.cost) if l.cost is not None else None}
        return {
            "direct": str(self.direct) if self.direct is not None else None, "downstream": str(self.downstream),
            "total": str(self.total), "label": self.label, "tier": self.tier, "sources": self.sources,
            "explanation": self.explanation, "upstream": [link(x) for x in self.upstream],
            "downstream_links": [link(x) for x in self.downstream_links], "chain_hint": self.chain_hint,
        }


def _name(o: Obligation) -> str:
    return o.biller_raw or TYPE_LABEL.get(o.type, o.type.replace("_", " ").lower())


def _days(d: date, today: date) -> str:
    n = (d - today).days
    return "today" if n == 0 else "tomorrow" if n == 1 else f"{-n} days ago" if n < 0 else f"in {n} days"


def assess(o: Obligation, all_obls: list[Obligation], today: date) -> Consequence:
    open_obls = [x for x in all_obls if x.status in OPEN and x.id != o.id]
    vehicles = {x.vehicle_ref for x in all_obls if x.vehicle_ref}
    d = direct_cost(o.type, o.amount)
    verified = [d.verified] if d.amount is not None else []
    sources = [d.source] if d.source else []
    explanation = [f"Direct: {d.why}" + (" — estimated" if d.amount is not None and not d.verified else "")]
    downstream = Decimal(0)
    down_links: list[Link] = []

    for rule in dependency_rules():
        if rule["from_type"] != o.type:
            continue
        w = Decimal(str(rule["weight"])) if rule["relation"] == "AFFECTS" else Decimal(1)
        if rule["to_type"] in VIRTUAL:
            vd = direct_cost(rule["to_type"], None)
            cost = (vd.amount or 0) * w
            downstream += cost
            verified.append(vd.verified)
            if vd.source:
                sources.append(vd.source)
            down_links.append(Link(None, VIRTUAL[rule["to_type"]], None, rule["relation"], rule["explanation"], cost, float(w)))
            continue
        for v in open_obls:
            if v.type == rule["to_type"] and _same_vehicle(o, v, vehicles):
                vd = direct_cost(v.type, v.amount)
                cost = (vd.amount or 0) * w
                downstream += cost
                verified.append(vd.verified)
                if vd.source:
                    sources.append(vd.source)
                down_links.append(Link(v.id, _name(v), v.due_date.isoformat(), rule["relation"], rule["explanation"], cost, float(w)))

    up_links = []
    for rule in dependency_rules():
        if rule["to_type"] != o.type:
            continue
        for u in open_obls:
            if u.type == rule["from_type"] and _same_vehicle(o, u, vehicles):
                up_links.append(Link(u.id, _name(u), u.due_date.isoformat(), rule["relation"], rule["explanation"], None,
                                     float(rule["weight"])))

    total = (d.amount or Decimal(0)) + downstream
    for l in down_links:
        explanation.append(f"{'Blocks' if l.relation == 'BLOCKS_RENEWAL' else 'Affects'} {l.label}: {l.explanation}")
    label = "UNKNOWN" if d.amount is None and not down_links else ("VERIFIED" if verified and all(verified) else "ESTIMATED")

    hint = None
    blocked = [l for l in down_links if l.relation == "BLOCKS_RENEWAL"]
    if blocked:
        hint = f"{_name(o)} expires {_days(o.due_date, today)} → {blocked[0].label} renewal will be blocked"
    elif up_links:
        u = up_links[0]
        ud = date.fromisoformat(u.due_date) if u.due_date else None
        hint = f"Needs a valid {u.label} first ({'expired' if ud and ud < today else 'expires ' + ud.strftime('%d %b') if ud else 'date unknown'})"
    return Consequence(d.amount, downstream.quantize(Decimal("1")), total.quantize(Decimal("1")), label,
                       tier(total), sorted(set(s for s in sources if s)), explanation, up_links, down_links, hint)


def what_if(o: Obligation, all_obls: list[Obligation], today: date) -> dict:
    c = assess(o, all_obls, today)
    effects = []
    after = o.due_date + timedelta(days=1)
    if c.direct is not None:
        what = "lapses" if o.type in ("PUC", "INSURANCE_VEHICLE", "INSURANCE_OTHER", "DRIVING_LICENCE") else "becomes overdue"
        effects.append({"date": after.isoformat(), "text": f"{_name(o)} {what} — {c.explanation[0].split(': ', 1)[1]}",
                        "amount": str(c.direct)})
    for l in c.downstream_links:
        when = l.due_date or after.isoformat()
        verb = "renewal is blocked → it lapses" if l.relation == "BLOCKS_RENEWAL" else "is at risk"
        effects.append({"date": when, "text": f"{l.label} {verb}. {l.explanation}", "amount": str(l.cost) if l.cost is not None else None})
    return {**c.as_dict(), "skipped": _name(o), "timeline_effects": sorted(effects, key=lambda e: e["date"])}
