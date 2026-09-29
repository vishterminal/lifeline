from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

MessageKind = Literal["DUE_NOTICE", "RENEWAL_NOTICE", "PAYMENT_CONFIRMATION", "RECEIPT", "OTHER"]


class Extraction(BaseModel):
    """Output of either extractor (spec AI-1 schema). For receipts and payment
    confirmations `due_date` holds the charge/payment date."""

    is_bill: bool = False
    message_kind: MessageKind = "OTHER"
    obligation_type: str | None = None
    biller: str | None = None
    amount: Decimal | None = None
    currency: str | None = "INR"
    due_date: date | None = None
    vehicle_ref: str | None = None
    recurrence_hint: Literal["MONTHLY", "ANNUAL"] | None = None
    date_year_inferred: bool = False
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    notes: str | None = None

    @field_validator("amount")
    @classmethod
    def _positive(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v <= 0:
            raise ValueError("amount must be > 0")
        return v.quantize(Decimal("0.01")) if v is not None else None

    def public(self) -> dict:
        d = self.model_dump(mode="json")
        return d
