"""SQLAlchemy row models for the provider limit catalog, pools, and audit.

Money and native amounts are stored as exact text. One native pool holds a
shared vendor balance once, and both operation views project that single row, so
a shared Firecrawl, Tavily, or Keenable balance is never duplicated across
operation rows. Rate observations and rate attempts live in their own tables so
the REST and MCP processes count the same window from one durable record.
"""

from sqlalchemy import Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from freesearch.persistence.storage import Base


class ProviderLimitRow(Base):
    """Catalog row: one provider, operation, and auth mode."""

    __tablename__ = "provider_limits"

    provider: Mapped[str] = mapped_column(Text, primary_key=True, nullable=True)
    operation: Mapped[str] = mapped_column(Text, primary_key=True, nullable=True)
    auth_mode: Mapped[str] = mapped_column(Text, primary_key=True, nullable=True)
    supported: Mapped[int] = mapped_column(Integer)
    transport_available: Mapped[int] = mapped_column(Integer)
    rate_json: Mapped[str | None] = mapped_column(Text)
    budget_json: Mapped[str | None] = mapped_column(Text)
    native_unit: Mapped[str | None] = mapped_column(Text)
    native_pool_id: Mapped[str | None] = mapped_column(Text)
    conversion_profile_json: Mapped[str] = mapped_column(Text)
    plan_name: Mapped[str | None] = mapped_column(Text)
    usage_url: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)


class NativePoolRow(Base):
    """Durable native funds shared by one or more operation views."""

    __tablename__ = "provider_native_pools"

    pool_id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=True)
    provider: Mapped[str] = mapped_column(Text)
    auth_mode: Mapped[str] = mapped_column(Text)
    native_unit: Mapped[str] = mapped_column(Text)
    remaining_text: Mapped[str | None] = mapped_column(Text)
    allowance_text: Mapped[str | None] = mapped_column(Text)
    actual_spend_usd_text: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(Text)
    reset_at: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    credential_generation: Mapped[int] = mapped_column(Integer)
    next_sync_at: Mapped[str | None] = mapped_column(Text)
    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_until: Mapped[str | None] = mapped_column(Text)
    sync_error_code: Mapped[str | None] = mapped_column(Text)
    stale: Mapped[int] = mapped_column(Integer)
    manual_anchor: Mapped[int] = mapped_column(Integer)
    tier_json: Mapped[str | None] = mapped_column(Text)
    tier_split_known: Mapped[int] = mapped_column(Integer)
    last_tier_observed_at: Mapped[str | None] = mapped_column(Text)


class CRDGrantRow(Base):
    """Operator grant of credit units per provider, operation, and period."""

    __tablename__ = "provider_crd_grants"

    provider: Mapped[str] = mapped_column(Text, primary_key=True, nullable=True)
    operation: Mapped[str] = mapped_column(Text, primary_key=True, nullable=True)
    auth_mode: Mapped[str] = mapped_column(Text, primary_key=True, nullable=True)
    period_start: Mapped[str] = mapped_column(Text, primary_key=True, nullable=True)
    period_end: Mapped[str] = mapped_column(Text)
    granted_crd_text: Mapped[str] = mapped_column(Text)
    consumed_crd_text: Mapped[str] = mapped_column(Text)
    reserved_crd_text: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)


class LimitEventRow(Base):
    """Immutable balance-change, denial, grant, or reset record."""

    __tablename__ = "provider_limit_events"
    __table_args__ = (
        UniqueConstraint("local_attempt_id", "reason", name="uq_limit_event_attempt_reason"),
        Index(
            "provider_limit_events_provider_auth_observed",
            "provider",
            "auth_mode",
            "observed_at",
            "event_id",
        ),
    )

    event_id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=True)
    provider: Mapped[str] = mapped_column(Text)
    operation: Mapped[str | None] = mapped_column(Text)
    auth_mode: Mapped[str] = mapped_column(Text)
    pool_id: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    old_native_text: Mapped[str | None] = mapped_column(Text)
    new_native_text: Mapped[str | None] = mapped_column(Text)
    old_crd_json: Mapped[str | None] = mapped_column(Text)
    new_crd_json: Mapped[str | None] = mapped_column(Text)
    crd_debit_text: Mapped[str | None] = mapped_column(Text)
    native_debit_text: Mapped[str | None] = mapped_column(Text)
    actual_usd_text: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(Text)
    local_attempt_id: Mapped[str | None] = mapped_column(Text)
    detail_json: Mapped[str | None] = mapped_column(Text)


class LimitAdmissionRow(Base):
    """Durable reservation that finalizes or releases exactly once."""

    __tablename__ = "provider_limit_admissions"
    __table_args__ = (Index("provider_limit_admissions_created_at", "created_at"),)

    attempt_id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=True)
    provider: Mapped[str] = mapped_column(Text)
    operation: Mapped[str] = mapped_column(Text)
    auth_mode: Mapped[str] = mapped_column(Text)
    pool_id: Mapped[str | None] = mapped_column(Text)
    reserved_crd_text: Mapped[str] = mapped_column(Text)
    reserved_native_text: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[str] = mapped_column(Text)
    rate_reservations_json: Mapped[str | None] = mapped_column(Text)
    local_only: Mapped[int] = mapped_column(Integer)


class RateWindowObservationRow(Base):
    """Newest durable observation of one rate bucket and window."""

    __tablename__ = "provider_rate_observations"

    bucket_id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=True)
    provider: Mapped[str] = mapped_column(Text, primary_key=True, nullable=True)
    auth_mode: Mapped[str] = mapped_column(Text, primary_key=True, nullable=True)
    window: Mapped[str] = mapped_column(Text, primary_key=True, nullable=True)
    unit: Mapped[str] = mapped_column(Text, primary_key=True, nullable=True)
    operation: Mapped[str | None] = mapped_column(Text)
    limit_text: Mapped[str | None] = mapped_column(Text)
    remaining_text: Mapped[str | None] = mapped_column(Text)
    reset_at: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(Text)
    stale: Mapped[int] = mapped_column(Integer)


class RateAttemptRow(Base):
    """One consumed rate unit, expiring by its own age or the vendor reset."""

    __tablename__ = "provider_rate_attempts"
    __table_args__ = (
        Index("provider_rate_attempts_bucket_attempted", "bucket_id", "attempted_at"),
        Index("provider_rate_attempts_expires_at", "expires_at"),
    )

    attempt_id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=True)
    bucket_id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=True)
    provider: Mapped[str] = mapped_column(Text)
    auth_mode: Mapped[str] = mapped_column(Text)
    operation: Mapped[str | None] = mapped_column(Text)
    window: Mapped[str] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(Text)
    units_text: Mapped[str] = mapped_column(Text)
    attempted_at: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[str] = mapped_column(Text)
