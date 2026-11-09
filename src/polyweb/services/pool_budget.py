"""Atomic calendar-window budget reservations for vault pools."""

from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from polyweb.models.budget_period import window_start
from polyweb.models.contracts import (
    FetchRequest,
    FetchResponse,
    ProviderError,
    SearchRequest,
    SearchResponse,
    UnitKind,
)
from polyweb.models.provider_limits import AuthMode, ProviderLimitRecord
from polyweb.services.credit_units import request_cost_crd
from polyweb.services.provider_limits import _debit_crd, _reported_native

_DAY = 86400
_WEEK = 604800
_MONTH = 2592000


def request_price(
    record: ProviderLimitRecord, request: SearchRequest | FetchRequest
) -> Decimal | None:
    """Price this request on its selected rail, not the routing sort price."""
    if record.auth_mode is AuthMode.KEYLESS and record.provider in {"tavily", "keenable"}:
        return Decimal(0)
    cost = request_cost_crd(record, request)
    return None if cost is None else cost * record.conversion_profile.reference_usd_per_crd


def actual_price(
    record: ProviderLimitRecord, response: SearchResponse | FetchResponse
) -> Decimal | None:
    """Return only a vendor-reported charge that can be converted to USD."""
    usage = response.usage
    if usage is None:
        return None
    if usage.unit_kind is UnitKind.USD:
        return usage.units
    native = _reported_native(response, record)
    crd = _debit_crd(record, native)
    return None if crd is None else crd * record.conversion_profile.reference_usd_per_crd


def failure_price(record: ProviderLimitRecord, error: ProviderError) -> Decimal | None:
    """Price a confirmed charge on a failed attempt, when one is reported."""
    details = error.details
    value = details.get("actual_usd")
    native = False
    if value is None and details.get("charged_document"):
        value = details.get("native_credits")
        native = True
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount < 0:
        return None
    if not native:
        return amount
    crd = _debit_crd(record, amount)
    return None if crd is None else crd * record.conversion_profile.reference_usd_per_crd


def price_micros(price: Decimal) -> int:
    return int((price * 1_000_000).to_integral_value(rounding=ROUND_CEILING))


async def settle_actual(
    session: AsyncSession, pool_id: UUID, reserved: int, actual: int, *, window_start: str
) -> None:
    """Replace the estimate with the reported charge in the original window."""
    await session.execute(
        text(
            "UPDATE pool_budget_usage SET spent_micros=spent_micros + :delta, updated_at=:updated "
            "WHERE pool_id=:pool AND window_start=:window AND spent_micros >= :reserved"
        ),
        {
            "pool": str(pool_id),
            "window": window_start,
            "reserved": reserved,
            "delta": actual - reserved,
            "updated": datetime.now(UTC).isoformat(),
        },
    )


async def reserve_with_window(
    session: AsyncSession, pool_id: UUID, cost_micros: int, *, now: datetime | None = None
) -> tuple[bool, str | None]:
    """Reserve against the current cap atomically; return its actual window for refunds."""
    if cost_micros < 0:
        raise ValueError("cost must be nonnegative")
    current = (
        await session.execute(
            text("SELECT budget_limit FROM key_pools WHERE id=:pool"), {"pool": str(pool_id)}
        )
    ).first()
    if current is None:
        raise ValueError("vault pool no longer exists")
    if current[0] is None:
        return True, None
    instant = now or datetime.now(UTC)
    params = {
        "pool": str(pool_id),
        "cost": cost_micros,
        "day": window_start(instant, _DAY),
        "week": window_start(instant, _WEEK),
        "month": window_start(instant, _MONTH),
        "updated": instant.astimezone(UTC).isoformat(),
    }
    result = await session.execute(
        text(
            "INSERT INTO pool_budget_usage (pool_id,window_start,spent_micros,updated_at) "
            "SELECT id, CASE budget_window_seconds WHEN 86400 THEN :day "
            "WHEN 604800 THEN :week ELSE :month END, :cost, :updated FROM key_pools "
            "WHERE id=:pool AND budget_limit IS NOT NULL AND :cost <= budget_limit "
            "ON CONFLICT(pool_id,window_start) DO UPDATE SET "
            "spent_micros=pool_budget_usage.spent_micros + excluded.spent_micros, "
            "updated_at=excluded.updated_at WHERE pool_budget_usage.spent_micros <= "
            "(SELECT budget_limit FROM key_pools WHERE id=:pool) - excluded.spent_micros "
            "RETURNING window_start"
        ),
        params,
    )
    row = result.first()
    if row is not None:
        return True, str(row[0])
    cap = await session.execute(text("SELECT budget_limit FROM key_pools WHERE id=:pool"), params)
    row = cap.first()
    if row is None:
        raise ValueError("vault pool no longer exists")
    return row[0] is None, None


async def reserve(
    session: AsyncSession, pool_id: UUID, cost_micros: int, *, now: datetime | None = None
) -> bool:
    """Reserve cost in the caller's transaction, or refuse an exhausted budget."""
    allowed, _ = await reserve_with_window(session, pool_id, cost_micros, now=now)
    return allowed


async def release(
    session: AsyncSession, pool_id: UUID, cost_micros: int, *, window_start: str
) -> None:
    """Refund an unsent call in its original window."""
    if cost_micros < 0:
        raise ValueError("cost must be nonnegative")
    await session.execute(
        text(
            "UPDATE pool_budget_usage SET spent_micros=spent_micros-:cost, updated_at=:updated "
            "WHERE pool_id=:pool AND window_start=:window AND spent_micros >= :cost"
        ),
        {
            "pool": str(pool_id),
            "window": window_start,
            "cost": cost_micros,
            "updated": datetime.now(UTC).isoformat(),
        },
    )


async def pool_budget_used_micros(
    session: AsyncSession, pool_id: UUID, *, now: datetime | None = None
) -> int:
    """Return spend in the pool's currently configured calendar window."""
    instant = now or datetime.now(UTC)
    result = await session.execute(
        text(
            "SELECT COALESCE(u.spent_micros, 0) FROM key_pools p "
            "LEFT JOIN pool_budget_usage u ON u.pool_id=p.id AND u.window_start="
            "CASE p.budget_window_seconds WHEN 86400 THEN :day WHEN 604800 THEN :week "
            "ELSE :month END WHERE p.id=:pool"
        ),
        {
            "pool": str(pool_id),
            "day": window_start(instant, _DAY),
            "week": window_start(instant, _WEEK),
            "month": window_start(instant, _MONTH),
        },
    )
    return int(result.scalar_one_or_none() or 0)
