"""'Ask Lifeline': answers questions about the user's own bills from their data.

Rule-based intent matching over the same engines the app uses (ranking, cash flow,
subscriptions), so answers are exact numbers, never guesses. Works in the app and on
WhatsApp (any message ending with '?')."""
from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Obligation, User
from app.services import risk_service
from app.timeutil import today_local

OPEN = ("OPEN", "OVERDUE")
SUGGESTIONS = [
    "What do I owe this week?", "What's most urgent?", "Anything overdue?",
    "How much do subscriptions cost me?", "Can I afford my bills before salary?", "When is my Netflix due?",
]


def _inr(v) -> str:
    return "amount unknown" if v is None else f"₹{Decimal(v):,.0f}"


def _line(o: Obligation, today) -> str:
    d = (o.due_date - today).days
    when = "today" if d == 0 else "tomorrow" if d == 1 else f"{-d} days overdue" if d < 0 else f"in {d} days ({o.due_date:%d %b})"
    return f"• {o.biller_raw or o.biller_norm} — {_inr(o.amount)}, {when}"


def answer(db: Session, user: User, question: str) -> dict:
    q = question.lower().strip()
    today = today_local()
    obls = list(db.scalars(select(Obligation).where(Obligation.user_id == user.id)))
    open_ = sorted([o for o in obls if o.status in OPEN], key=lambda o: o.due_date)

    def window(days: int) -> list[Obligation]:
        return [o for o in open_ if (o.due_date - today).days <= days]

    if not open_ and not re.search(r"subscri|help|what can", q):
        return {"answer": "You have no open bills right now. 🎉 Connect a source or run the demo to get started.", "intent": "empty"}

    if re.search(r"overdue|late|missed", q):
        late = [o for o in open_ if o.due_date < today]
        text = "Nothing is overdue. 👍" if not late else "Overdue:\n" + "\n".join(_line(o, today) for o in late) + \
            "\nOpen the bill in Bills → Penalty Fighter to draft a late-fee waiver request."
        return {"answer": text, "intent": "overdue"}

    if re.search(r"urgent|risk|priorit|first|most important|biggest", q):
        ranked = sorted(open_, key=lambda o: -risk_service.assess(o, obls, today).total)[:3]
        lines = []
        for o in ranked:
            c = risk_service.assess(o, obls, today)
            lines.append(_line(o, today) + f" · {_inr(c.total)} at risk ({c.label.lower()})" + (f"\n  ⛓ {c.chain_hint}" if c.chain_hint else ""))
        return {"answer": "Most urgent by what missing it would cost:\n" + "\n".join(lines), "intent": "risk"}

    if re.search(r"subscri|netflix bill total|streaming", q) and not re.search(r"when|due", q):
        subs = [o for o in open_ if o.is_recurring]
        monthly = sum((o.amount * Decimal(30) / Decimal(o.recurrence_interval_days or 30) for o in subs if o.amount), Decimal(0))
        if not subs:
            return {"answer": "No subscriptions detected yet.", "intent": "subscriptions"}
        return {"answer": f"{len(subs)} subscription(s) cost about {_inr(monthly)} a month ({_inr(monthly * 12)} a year):\n"
                + "\n".join(_line(o, today) for o in subs), "intent": "subscriptions"}

    if re.search(r"afford|enough|salary|balance|cash", q):
        if user.balance_amount is None:
            return {"answer": "Add your balance (and salary day) in Settings and I can check that.", "intent": "cashflow"}
        horizon = None
        if user.salary_day:
            for i in range(1, 32):
                d = today + timedelta(days=i)
                if d.day == user.salary_day:
                    horizon = d
                    break
        due = [o for o in open_ if o.amount and (horizon is None or o.due_date < horizon)]
        total = sum((o.amount for o in due), Decimal(0))
        bal = Decimal(user.balance_amount)
        until = f"before salary on {horizon:%d %b}" if horizon else "coming up"
        if total <= bal:
            return {"answer": f"Yes. Bills {until} total {_inr(total)}; your balance is {_inr(bal)}, leaving {_inr(bal - total)}.", "intent": "cashflow"}
        return {"answer": f"Not quite. Bills {until} total {_inr(total)} but your balance is {_inr(bal)} — short by {_inr(total - bal)}. "
                "See Cash flow for which to pay first.", "intent": "cashflow"}

    m = re.search(r"(?:when|how much).*?(?:is|does|for|my)\s+([a-z][a-z0-9 .&-]{2,30}?)(?:\s+(?:due|bill|cost|renew))?\??$", q)
    if m:
        name = m.group(1).strip().removeprefix("my ").strip()
        hits = [o for o in open_ if name and name in (o.biller_raw or "").lower() or name in (o.biller_norm or "")]
        if hits:
            return {"answer": "\n".join(_line(o, today) for o in hits), "intent": "lookup"}

    for days, label in ((0, "today"), (1, "by tomorrow"), (7, "this week"), (31, "this month")):
        words = {0: r"today", 1: r"tomorrow", 7: r"week|7 days", 31: r"month|30 days"}[days]
        if re.search(words, q):
            items = window(days)
            total = sum((o.amount for o in items if o.amount), Decimal(0))
            if not items:
                return {"answer": f"Nothing due {label}.", "intent": "window"}
            return {"answer": f"{len(items)} bill(s) due {label}, {_inr(total)} in total:\n" + "\n".join(_line(o, today) for o in items), "intent": "window"}

    if re.search(r"owe|due|pending|bills?|total", q):
        total = sum((o.amount for o in open_ if o.amount), Decimal(0))
        return {"answer": f"{len(open_)} open bill(s), {_inr(total)} in total. Next up:\n" + "\n".join(_line(o, today) for o in open_[:4]), "intent": "summary"}

    return {"answer": "I can answer questions about your bills. Try:\n" + "\n".join(f"• {s}" for s in SUGGESTIONS), "intent": "help"}
