from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import OBLIGATION_TYPES

E164 = re.compile(r"^\+[1-9]\d{6,14}$")


def _e164(v: str | None) -> str | None:
    if v in (None, ""):
        return None
    v = v.replace(" ", "")
    if not E164.match(v):
        raise ValueError("phone must be E.164, e.g. +919876543210")
    return v


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str | None = Field(None, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    name: str | None
    phone_e164: str | None
    salary_day: int | None
    balance_amount: Decimal | None
    salary_amount: Decimal | None = None
    balance_as_of: datetime | None
    allow_cloud_image_processing: bool
    whatsapp_last_inbound_at: datetime | None
    is_demo: bool = False


class AuthOut(BaseModel):
    token: str
    user: UserOut


class ProfileIn(BaseModel):
    name: str | None = Field(None, max_length=200)
    phone_e164: str | None = None
    salary_day: int | None = Field(None, ge=1, le=31)
    balance_amount: Decimal | None = Field(None, ge=0)
    salary_amount: Decimal | None = Field(None, ge=0)
    balance_as_of: datetime | None = None
    allow_cloud_image_processing: bool | None = None

    _p = field_validator("phone_e164")(classmethod(lambda cls, v: _e164(v)))


class WhatsAppLinkIn(BaseModel):
    phone_e164: str

    _p = field_validator("phone_e164")(classmethod(lambda cls, v: _e164(v)))


class ManualIn(BaseModel):
    biller: str = Field(min_length=1, max_length=200)
    type: str = "OTHER"
    amount: Decimal | None = Field(None, gt=0)
    due_date: date
    vehicle_ref: str | None = Field(None, max_length=40)
    recurring: Literal["MONTHLY", "ANNUAL"] | None = None
    review: bool = False  # send to Review for a final check instead of saving straight away

    @field_validator("type")
    @classmethod
    def _type(cls, v: str) -> str:
        if v not in OBLIGATION_TYPES:
            raise ValueError(f"type must be one of {', '.join(OBLIGATION_TYPES)}")
        return v


class ConfirmationFields(BaseModel):
    biller: str | None = Field(None, max_length=200)
    type: str | None = None
    amount: Decimal | None = Field(None, gt=0)
    due_date: date | None = None
    vehicle_ref: str | None = None
    message_kind: Literal["DUE_NOTICE", "RENEWAL_NOTICE", "PAYMENT_CONFIRMATION", "RECEIPT", "OTHER"] | None = None

    @field_validator("type")
    @classmethod
    def _type(cls, v):
        if v is not None and v not in OBLIGATION_TYPES:
            raise ValueError("invalid type")
        return v


class ResolveIn(BaseModel):
    action: Literal["confirm", "reject"]
    fields: ConfirmationFields | None = None


class ObligationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    origin: str
    type: str
    biller_raw: str | None
    biller_norm: str | None
    amount: Decimal | None
    currency: str
    due_date: date
    status: str
    source_kinds: list
    trust_label: str
    trust_score: int | None
    confidence: float
    extractors_agreed: bool
    message_kind: str | None
    vehicle_ref: str | None
    is_recurring: bool
    recurrence_interval_days: int | None
    next_expected_date: date | None
    price_changed: bool
    paid_via: str | None
    created_at: datetime


class ConfirmationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    origin: str
    source_kind: str
    draft: dict
    reason: str
    status: str
    obligation_id: str | None
    created_at: datetime


class FlaggedOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    origin: str
    source_kind: str
    sender: str | None
    claimed_biller: str | None
    claimed_amount: Decimal | None
    reasons: list
    risk_score: int
    dismissed: bool
    created_at: datetime


class IngestEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    source_kind: str
    received_at: datetime
    outcome: str
    obligation_id: str | None
    reference_id: str | None
    reason: str | None


class SimulateTextIn(BaseModel):
    text: str | None = Field(None, max_length=20_000)
    fixture: str | None = None
    sender: str | None = None
