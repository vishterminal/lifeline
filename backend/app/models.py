"""SQLAlchemy models for the input side (spec Section 9.1).

IMPLEMENTATION DECISION: enums are stored as plain strings (portable between
SQLite and PostgreSQL); allowed values live in the constants below.
Output-side tables (reminders, payments, penalty rules, ...) are not built yet.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


SOURCE_KINDS = ("GMAIL", "SMS", "WHATSAPP", "UPLOAD", "MANUAL", "STATEMENT", "DEMO")
SOURCE_STATUSES = ("CONNECTED", "NEEDS_RECONNECT", "DISCONNECTED", "ERROR")
INGEST_OUTCOMES = (
    "DROPPED_NOT_BILL", "DROPPED_OTP", "DUPLICATE", "SUSPICIOUS",
    "NEEDS_CONFIRMATION", "SAVED", "PAID_DETECTED", "CHARGE_RECORDED", "FAILED",
)
OBLIGATION_TYPES = (
    "ELECTRICITY", "WATER", "GAS", "PHONE_INTERNET", "INSURANCE_VEHICLE", "INSURANCE_OTHER",
    "PUC", "DRIVING_LICENCE", "VEHICLE_OTHER", "SUBSCRIPTION", "LOAN_EMI", "APPOINTMENT",
    "DOCUMENT_OTHER", "OTHER",
)
OBLIGATION_STATUSES = ("OPEN", "PAID", "DISMISSED", "OVERDUE")
TRUST_LABELS = ("VERIFIED_SENDER", "UNVERIFIED", "NEW_BILLER_CONFIRM", "SUSPICIOUS", "NOT_APPLICABLE")
CONFIRMATION_REASONS = ("EXTRACTION_MISMATCH", "LOW_CONFIDENCE", "NEW_BILLER", "MEDIUM_TRUST", "MISSING_FIELDS", "RECURRING_CANDIDATE")


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True)  # "Continue with Google"
    # Judge demo account: every source runs on sample data, even when live keys are configured.
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    name: Mapped[str | None] = mapped_column(String(200))
    phone_e164: Mapped[str | None] = mapped_column(String(20), index=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    salary_day: Mapped[int | None] = mapped_column(Integer)
    balance_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    balance_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    allow_cloud_image_processing: Mapped[bool] = mapped_column(Boolean, default=False)
    quiet_start: Mapped[time] = mapped_column(Time, default=time(21, 0))
    quiet_end: Mapped[time] = mapped_column(Time, default=time(8, 0))
    repeat_cap: Mapped[int] = mapped_column(Integer, default=3)
    whatsapp_last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConnectedSource(Base):
    __tablename__ = "connected_sources"
    __table_args__ = (UniqueConstraint("user_id", "kind"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="DISCONNECTED")
    gmail_address: Mapped[str | None] = mapped_column(String(320))
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text)
    gmail_cursor_ms: Mapped[int | None] = mapped_column(BigInteger)
    oauth_state: Mapped[str | None] = mapped_column(String(128))
    ingest_token_hash: Mapped[str | None] = mapped_column(String(128))
    ingest_token_prefix: Mapped[str | None] = mapped_column(String(16), index=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IngestEvent(Base):
    """Audit log. Never holds a message body — only a hash and the outcome."""
    __tablename__ = "ingest_events"
    __table_args__ = (Index("ix_ingest_user_hash", "user_id", "content_hash"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source_kind: Mapped[str] = mapped_column(String(20))
    content_hash: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    outcome: Mapped[str] = mapped_column(String(30))
    obligation_id: Mapped[str | None] = mapped_column(String(36))
    reference_id: Mapped[str | None] = mapped_column(String(36))
    reason: Mapped[str | None] = mapped_column(String(300))


class Obligation(Base):
    __tablename__ = "obligations"
    __table_args__ = (Index("ix_obl_user_status_due", "user_id", "status", "due_date"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    origin: Mapped[str] = mapped_column(String(10), default="REAL")
    type: Mapped[str] = mapped_column(String(30), default="OTHER")
    biller_raw: Mapped[str | None] = mapped_column(String(200))
    biller_norm: Mapped[str | None] = mapped_column(String(200), index=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(12), default="OPEN")
    source_kinds: Mapped[list] = mapped_column(JSON, default=list)
    trust_label: Mapped[str] = mapped_column(String(24), default="NOT_APPLICABLE")
    trust_score: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    extractors_agreed: Mapped[bool] = mapped_column(Boolean, default=False)
    message_kind: Mapped[str | None] = mapped_column(String(24))
    vehicle_ref: Mapped[str | None] = mapped_column(String(40))
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False)
    recurrence_interval_days: Mapped[int | None] = mapped_column(Integer)
    next_expected_date: Mapped[date | None] = mapped_column(Date)
    price_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    early_discount_pct: Mapped[float | None] = mapped_column(Float)
    early_discount_until: Mapped[date | None] = mapped_column(Date)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_via: Mapped[str | None] = mapped_column(String(20))
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PendingConfirmation(Base):
    __tablename__ = "pending_confirmations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    origin: Mapped[str] = mapped_column(String(10), default="REAL")
    source_kind: Mapped[str] = mapped_column(String(20))
    draft: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(12), default="PENDING")
    obligation_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FlaggedItem(Base):
    """Suspicious messages. No body/subject stored."""
    __tablename__ = "flagged_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    origin: Mapped[str] = mapped_column(String(10), default="REAL")
    source_kind: Mapped[str] = mapped_column(String(20))
    sender: Mapped[str | None] = mapped_column(String(320))
    claimed_biller: Mapped[str | None] = mapped_column(String(200))
    claimed_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    risk_score: Mapped[int] = mapped_column(Integer)
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChargeEvent(Base):
    __tablename__ = "charge_events"
    __table_args__ = (Index("ix_charge_user_merchant_date", "user_id", "merchant_norm", "charge_date"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    origin: Mapped[str] = mapped_column(String(10), default="REAL")
    charge_date: Mapped[date] = mapped_column(Date)
    merchant_norm: Mapped[str] = mapped_column(String(200))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    source: Mapped[str] = mapped_column(String(20))  # STATEMENT | RECEIPT | SMS_DEBIT
    obligation_id: Mapped[str | None] = mapped_column(String(36))


class BillerAlias(Base):
    __tablename__ = "biller_aliases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    canonical_name: Mapped[str] = mapped_column(String(100), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    category: Mapped[str] = mapped_column(String(50))
    default_type: Mapped[str] = mapped_column(String(30))
    official_domains: Mapped[list] = mapped_column(JSON, default=list)
    sender_ids: Mapped[list] = mapped_column(JSON, default=list)
    official_account_url: Mapped[str | None] = mapped_column(String(300))
    behavior: Mapped[dict] = mapped_column(JSON, default=dict)
    billing_cycle_days: Mapped[int | None] = mapped_column(Integer)
    # False until domains/sender IDs are checked against the real ones; the trust
    # check never awards VERIFIED_SENDER for an unverified reference row.
    reference_verified: Mapped[bool] = mapped_column(Boolean, default=False)


class Consent(Base):
    __tablename__ = "consents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Payment(Base):
    """Mocked one-tap pay (spec F17). No real money moves; is_mock is always True."""
    __tablename__ = "payments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    obligation_id: Mapped[str] = mapped_column(ForeignKey("obligations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    is_mock: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
