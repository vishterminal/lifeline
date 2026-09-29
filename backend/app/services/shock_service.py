"""Bill-shock alert: a bill much higher than what you usually pay that biller.

"Usual" = median of your earlier bills from the same biller (and statement charges not
tied to a bill). Only increases are flagged; one earlier bill is enough to compare."""
from __future__ import annotations

import statistics
from decimal import Decimal

from app.models import Obligation

SHOCK_PCT = 25  # same threshold the fake-bill check uses for "amount differs from your usual"


def bill_shock(o: Obligation, all_obls: list[Obligation]) -> dict | None:
    if o.amount is None or not o.biller_norm or o.is_recurring:
        return None  # subscriptions have their own "price changed" flag
    earlier = sorted((x for x in all_obls if x.id != o.id and x.biller_norm == o.biller_norm
                      and x.amount is not None and x.due_date < o.due_date), key=lambda x: x.due_date)
    if not earlier:
        return None
    usual = Decimal(str(statistics.median([x.amount for x in earlier]))).quantize(Decimal("0.01"))
    if usual <= 0:
        return None
    pct = int((o.amount - usual) / usual * 100)
    if pct < SHOCK_PCT:
        return None
    history = [{"date": x.due_date.isoformat(), "amount": str(x.amount)} for x in earlier[-5:]]
    history.append({"date": o.due_date.isoformat(), "amount": str(o.amount)})
    return {"usual": str(usual), "pct": pct, "extra": str(o.amount - usual), "based_on": len(earlier), "history": history}
