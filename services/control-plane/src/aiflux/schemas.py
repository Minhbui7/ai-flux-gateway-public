from datetime import datetime
from decimal import Decimal
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SubscriptionCreate(Input):
    name: str = Field(min_length=1, max_length=100)
    team: str = Field(min_length=1, max_length=100)


class KeyRequest(Input):
    key: Literal["primary", "secondary"] = "primary"


class StateRequest(Input):
    state: Literal["active", "suspended"]


class OrganizationCreate(Input):
    name: str = Field(min_length=1, max_length=100)
    tenant_id: UUID


class EnabledRequest(Input):
    enabled: bool


class MemberCreate(Input):
    organization_id: UUID
    object_id: UUID
    role: Literal["customer", "ids_admin"] = "customer"


class PriceCreate(Input):
    model: str = Field(min_length=1, max_length=100)
    provider: str = Field(min_length=1, max_length=60)
    region: str = Field(min_length=1, max_length=60)
    effective_from: datetime
    effective_to: datetime | None = None
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    input_per_million: Decimal = Field(ge=0, max_digits=20, decimal_places=8)
    output_per_million: Decimal = Field(ge=0, max_digits=20, decimal_places=8)
    cached_input_per_million: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=8)
    cache_write_per_million: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=8)
    input_includes_cached: bool = True

    @field_validator("effective_from", "effective_to")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Price effective dates require an explicit timezone")
        return value

    @model_validator(mode="after")
    def valid_period(self) -> "PriceCreate":
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be later than effective_from")
        return self


class PriceEnd(Input):
    effective_to: datetime

    @field_validator("effective_to")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Price effective dates require an explicit timezone")
        return value


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int


class IdentityOutput(BaseModel):
    organization_id: str
    organization_name: str
    tenant_id: str
    object_id: str
    role: Literal["customer", "ids_admin"]


class CatalogOutput(BaseModel):
    id: str
    provider: str
    capabilities: list[str]
    enabled: bool


class SubscriptionOutput(BaseModel):
    id: str
    name: str
    team: str
    state: Literal["pending", "active", "suspended", "failed"]
    created_at: datetime


class OrganizationOutput(BaseModel):
    id: str
    name: str
    tenant_id: str
    enabled: bool


class MemberOutput(BaseModel):
    id: str
    organization_id: str
    object_id: str
    role: Literal["customer", "ids_admin"]
    enabled: bool


class PriceOutput(PriceCreate):
    id: str


class UsageOutput(BaseModel):
    id: str
    subscription_id: str
    model: str
    provider: str
    region: str
    occurred_at: datetime
    input_tokens: int | None
    output_tokens: int | None
    cached_input_tokens: int | None
    cache_write_tokens: int | None
    cost: str | None
    currency: str | None
    status_code: int
    e2e_ms: int | None
    ttft_ms: int | None
    completeness: str


class UsageSummary(BaseModel):
    requests: int
    input_tokens: int
    output_tokens: int
    known_cost: str | None
    currency: str | None
    incomplete_requests: int
    failed_requests: int
    throttled_requests: int
    e2e_p95_ms: int | None
    ttft_supported: bool
    cache_tokens_supported: bool
    last_ingested_at: datetime | None


class UsagePage(Page[UsageOutput]):
    summary: UsageSummary


class SafetyOutput(BaseModel):
    id: str
    organization_id: str
    subscription_id: str
    occurred_at: datetime
    category: str
    action: str
    correlation_id: str
