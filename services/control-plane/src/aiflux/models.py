from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100))
    tenant_id: Mapped[str] = mapped_column(String(36), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Member(Base):
    __tablename__ = "members"
    __table_args__ = (
        UniqueConstraint("organization_id", "object_id"),
        CheckConstraint("role IN ('customer', 'ids_admin')"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    object_id: Mapped[str] = mapped_column(String(36))
    role: Mapped[str] = mapped_column(String(20), default="customer")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class TeamSubscription(Base):
    __tablename__ = "team_subscriptions"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key"),
        CheckConstraint("state IN ('pending', 'active', 'suspended', 'failed')"),
        CheckConstraint("desired_state IN ('active', 'suspended')"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    team: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(20), default="pending")
    desired_state: Mapped[str] = mapped_column(String(20), default="active")
    idempotency_key: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    object_id: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(60))
    target_id: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModelPrice(Base):
    __tablename__ = "model_prices"
    __table_args__ = (
        Index("ix_price_lookup", "model", "provider", "region", "effective_from"),
        CheckConstraint("input_per_million >= 0 AND output_per_million >= 0"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    model: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(60))
    region: Mapped[str] = mapped_column(String(60))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    currency: Mapped[str] = mapped_column(String(3))
    input_per_million: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    output_per_million: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    cached_input_per_million: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    cache_write_per_million: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    input_includes_cached: Mapped[bool] = mapped_column(Boolean, default=True)


class UsageRecord(Base):
    __tablename__ = "usage_records"
    __table_args__ = (Index("ix_usage_org_time", "organization_id", "occurred_at"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    subscription_id: Mapped[str] = mapped_column(ForeignKey("team_subscriptions.id"), index=True)
    model: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(60))
    region: Mapped[str] = mapped_column(String(60))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cached_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    status_code: Mapped[int] = mapped_column(Integer)
    e2e_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ttft_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completeness: Mapped[str] = mapped_column(String(100))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SafetyEvent(Base):
    __tablename__ = "safety_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    subscription_id: Mapped[str] = mapped_column(ForeignKey("team_subscriptions.id"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    category: Mapped[str] = mapped_column(String(60))
    action: Mapped[str] = mapped_column(String(60))
    correlation_id: Mapped[str] = mapped_column(String(100))


class IngestionState(Base):
    __tablename__ = "ingestion_state"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    watermark: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
