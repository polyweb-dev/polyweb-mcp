"""Failure settlement must follow one rule on the legacy and native paths.

The ``error is None`` branch of ``_finalize_native_failure`` is not covered here:
the legacy path only settles an ``Exception``, so it never passes ``None``.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest

from polyweb.models.contracts import ProviderError
from polyweb.services.monitoring import _finalize_capacity_path, _finalize_native_failure

PROVIDER = "tavily"
CHARGE_DETAILS = {"native_credits": "2", "charged_document": True, "actual_usd": "0.01"}


@dataclass(frozen=True)
class FakeAdmission:
    provider: str = PROVIDER


@dataclass
class SpyLimits:
    failures: list[tuple[Any, ProviderError, dict[str, Any]]] = field(default_factory=list)

    async def record_failure(self, admission: Any, error: ProviderError, **charges: Any) -> None:
        self.failures.append((admission, error, charges))


class PayloadError(Exception):
    def __init__(self, payload: object) -> None:
        super().__init__("payload failure")
        self.error = payload


class BareError(Exception):
    pass


@dataclass
class DuckProviderError:
    details: dict[str, Any] = field(default_factory=lambda: dict(CHARGE_DETAILS))


async def _settle_legacy(limits: SpyLimits, admission: FakeAdmission, exc: Exception) -> None:
    await _finalize_capacity_path(
        charger=None,
        limits=limits,  # type: ignore[arg-type]
        admission=admission,
        cancelled=False,
        failure=exc,
        response=None,
        request=None,
    )


async def _settle_native(limits: SpyLimits, admission: FakeAdmission, exc: Exception) -> None:
    await _finalize_native_failure(limits, admission, exc, request=None)  # type: ignore[arg-type]


def _uncharged(charges: dict[str, Any]) -> bool:
    return charges.get("charged_native") is None and not charges.get("charged_document")


Settle = Callable[[SpyLimits, FakeAdmission, Exception], Awaitable[None]]
PATHS = pytest.mark.parametrize(
    "settle", [_settle_legacy, _settle_native], ids=["legacy", "native"]
)


@PATHS
@pytest.mark.parametrize(
    "exc",
    [
        PayloadError("rate limited"),
        PayloadError({"code": "upstream_error", **CHARGE_DETAILS}),
        PayloadError(DuckProviderError()),
        BareError("no payload"),
    ],
    ids=["str", "dict", "duck", "missing"],
)
async def test_non_provider_error_payload_records_uncharged_local_failure(
    settle: Settle, exc: Exception
) -> None:
    limits, admission = SpyLimits(), FakeAdmission()

    await settle(limits, admission, exc)

    assert len(limits.failures) == 1, "record_failure must run exactly once"
    [(recorded_admission, error, charges)] = limits.failures
    assert recorded_admission == admission
    assert error == ProviderError(
        provider=PROVIDER,
        code=type(exc).__name__,
        message="local call failure",
        retryable=False,
    )
    assert _uncharged(charges)


@PATHS
async def test_provider_error_with_charge_details_records_confirmed_charge(
    settle: Settle,
) -> None:
    limits, admission = SpyLimits(), FakeAdmission()
    provider_error = ProviderError(
        provider=PROVIDER,
        code="upstream_error",
        message="vendor failed",
        retryable=True,
        status_code=502,
        details=dict(CHARGE_DETAILS),
    )

    await settle(limits, admission, PayloadError(provider_error))

    assert limits.failures == [
        (
            admission,
            provider_error,
            {"charged_native": Decimal("2"), "charged_document": True},
        )
    ]


@PATHS
async def test_provider_error_without_charge_details_records_no_charge(settle: Settle) -> None:
    limits, admission = SpyLimits(), FakeAdmission()
    provider_error = ProviderError(provider=PROVIDER, code="timeout", message="slow")

    await settle(limits, admission, PayloadError(provider_error))

    assert len(limits.failures) == 1, "record_failure must run exactly once"
    [(recorded_admission, error, charges)] = limits.failures
    assert recorded_admission == admission
    assert error == provider_error
    assert _uncharged(charges)
