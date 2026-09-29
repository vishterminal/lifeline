"""R-RECONCILE: compare Extractor A (LLM) and B (rules). Never auto-select
between two different numbers or dates."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.services.extraction.types import Extraction

COMPARED = ("biller_norm", "amount", "due_date", "message_kind")


@dataclass
class Reconciled:
    fields: Extraction  # best merged view (only used as-is when agreed)
    agreed: bool
    confidence: float
    mismatches: list[str] = field(default_factory=list)
    reason: str | None = None  # EXTRACTION_MISMATCH | LOW_CONFIDENCE | None
    candidates: dict = field(default_factory=dict)


def reconcile(a: Extraction | None, b: Extraction, norm_a: str | None, norm_b: str | None,
              llm_failure: str | None = None) -> Reconciled:
    cand = {"rules": {**b.public(), "biller_norm": norm_b}}
    if a is None:
        return Reconciled(b, False, min(b.confidence, 0.5), [], "LOW_CONFIDENCE",
                          {**cand, "llm": None, "llm_failure": llm_failure})
    cand["llm"] = {**a.public(), "biller_norm": norm_a}

    values = {
        "biller_norm": (norm_a, norm_b),
        "amount": (a.amount, b.amount),
        "due_date": (a.due_date, b.due_date),
        "message_kind": (a.message_kind, b.message_kind),
    }
    mismatches = [k for k, (x, y) in values.items() if x is not None and y is not None and x != y]
    partial = [k for k, (x, y) in values.items() if (x is None) != (y is None)]

    merged = a.model_copy(update={
        "biller": a.biller or b.biller,
        "amount": a.amount if a.amount is not None else b.amount,
        "due_date": a.due_date if a.due_date is not None else b.due_date,
        "obligation_type": a.obligation_type if a.obligation_type not in (None, "OTHER") else b.obligation_type,
        "vehicle_ref": a.vehicle_ref or b.vehicle_ref,
        "recurrence_hint": a.recurrence_hint or b.recurrence_hint,
        "date_year_inferred": a.date_year_inferred or b.date_year_inferred,
    })
    if mismatches:
        return Reconciled(merged, False, min(a.confidence, b.confidence), mismatches,
                          "EXTRACTION_MISMATCH", cand)
    if partial:
        # One extractor found a value the other missed: not a conflict, but not
        # corroborated either.
        conf = round(min(a.confidence, 0.75), 2)
        return Reconciled(merged, False, conf, [], None, cand)
    conf = round(min(max(a.confidence, b.confidence) + 0.05, 0.99), 2)
    return Reconciled(merged, True, conf, [], None, cand)
