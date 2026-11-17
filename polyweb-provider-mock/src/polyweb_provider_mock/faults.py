"""Fault rule definitions and the plan that one request draws from them.

A rule targets a provider (or ``*``) and an operation (or ``*``). Each request
evaluates the enabled rules in creation order: every firing ``latency`` rule
adds its delay, and the first firing rule of any other kind decides the
outcome. ``probability`` is the chance that a rule fires on one request,
``count`` limits how many times it fires, and ``duration`` ends it.
"""

import re
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "FaultKind",
    "FaultParams",
    "FaultPlan",
    "FaultRule",
    "FaultSpec",
    "MalformedVariant",
    "parse_duration",
]


class FaultKind(StrEnum):
    """What a fault rule does to a request."""

    LATENCY = "latency"
    TIMEOUT = "timeout"
    HTTP_ERROR = "http_error"
    OUTAGE = "outage"
    RATE_LIMIT = "rate_limit"
    QUOTA_EXHAUSTED = "quota_exhausted"
    AUTH_INVALID = "auth_invalid"
    MALFORMED = "malformed"
    CONNECTION_DROP = "connection_drop"


#: How a ``malformed`` rule damages an otherwise successful response.
MalformedVariant = Literal["invalid_json", "truncated", "wrong_content_type", "missing_field"]


class FaultParams(BaseModel):
    """Kind-specific parameters. Unused fields are ignored by other kinds.

    - ``latency``: ``ms`` plus a uniform ``jitter_ms``.
    - ``timeout``: hold the request for ``seconds`` (default 30, longer than
      Polyweb's default client timeout), then close the connection without a
      response. With ``status`` (for example 504) it answers that status in
      the provider's format after the hold instead.
    - ``http_error`` / ``outage``: ``status`` (defaults 500 / 503) and ``message``.
    - ``rate_limit``: ``retry_after`` seconds (default 60). ``retry_after_header``
      false keeps the delay in the body only, where the provider format has one.
    - ``quota_exhausted``: optional provider ``status`` (for example Tavily 432,
      433, or 402) and ``scope`` (``account``, ``key``, ``paygo``).
    - ``malformed``: ``variant``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ms: float | None = Field(default=None, ge=0)
    jitter_ms: float | None = Field(default=None, ge=0)
    seconds: float | None = Field(default=None, ge=0)
    status: int | None = Field(default=None, ge=100, le=599)
    message: str | None = None
    retry_after: int | None = Field(default=None, ge=0)
    retry_after_header: bool = True
    scope: str | None = None
    variant: MalformedVariant | None = None


class FaultSpec(BaseModel):
    """A rule to add: target, kind, firing chance, and lifetime."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = "*"
    operation: str = "*"
    kind: FaultKind
    params: FaultParams = Field(default_factory=FaultParams)
    probability: float = Field(default=1.0, ge=0.0, le=1.0)
    count: int | None = Field(default=None, ge=1)
    duration_seconds: float | None = Field(default=None, gt=0)
    enabled: bool = True
    scenario: str | None = None


class FaultRule(BaseModel):
    """A stored rule."""

    model_config = ConfigDict(frozen=True)

    id: int
    provider: str
    operation: str
    kind: FaultKind
    params: FaultParams
    probability: float
    remaining: int | None
    expires_at: datetime | None
    enabled: bool
    scenario: str | None
    created_at: datetime

    def active(self, now: datetime) -> bool:
        """Return whether the rule can still fire."""

        if not self.enabled or self.remaining == 0:
            return False
        return self.expires_at is None or now < self.expires_at

    @property
    def label(self) -> str:
        return f"{self.kind.value}#{self.id}"


class FaultPlan(BaseModel):
    """The faults one request draws: a total added delay and at most one outcome."""

    model_config = ConfigDict(frozen=True)

    delay_seconds: float = 0.0
    action: FaultRule | None = None
    fired: tuple[str, ...] = ()

    @property
    def label(self) -> str | None:
        return ",".join(self.fired) or None


_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(ms|s|m|h|d)?\s*$")
_UNIT_SECONDS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}


def parse_duration(text: str) -> float:
    """Parse ``500ms``, ``30s``, ``10m``, ``2h``, ``1d``, or plain seconds."""

    match = _DURATION.match(text)
    if match is None:
        raise ValueError(f"invalid duration {text!r}; use for example 30s, 10m, or 2h")
    return float(match.group(1)) * _UNIT_SECONDS[match.group(2) or "s"]
