"""State records and seed declarations shared by the store, the CLI, and plugins."""

import hashlib
import secrets
import string
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "Account",
    "AccountSeed",
    "ApiKey",
    "Fixture",
    "KeyFormat",
    "KeySeed",
    "KeylessSeed",
    "KeylessSetting",
    "LedgerEntry",
    "LogEntry",
    "PriceRule",
    "PricingRule",
    "ProviderSeed",
    "ResetRule",
]

#: When an account's used credits return to zero.
ResetRule = Literal["monthly", "daily", "none"]

#: ``per_unit`` debits ``credits_per_unit * units`` on every call.
#: ``accumulate`` adds that amount to a per-account carry and debits (and
#: reports) only the whole credits the carry crosses, as Tavily extract does.
PricingRule = Literal["per_unit", "accumulate"]


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True)


class KeyFormat(_Record):
    """The shape of a provider's real keys: a fixed prefix and a random body.

    Mock keys start the body with ``mock``, so they match the provider's key
    pattern but are visibly fake.
    """

    prefix: str = ""
    body_length: int = 32
    alphabet: str = string.ascii_letters + string.digits

    def generate(self, seed: str | None = None) -> str:
        """Return a new key; a ``seed`` makes the key repeatable."""

        size = max(self.body_length - 4, 1)
        if seed is None:
            body = "".join(secrets.choice(self.alphabet) for _ in range(size))
        else:
            digest = hashlib.sha256(seed.encode("utf-8")).digest()
            while len(digest) < size:
                digest += hashlib.sha256(digest).digest()
            body = "".join(self.alphabet[byte % len(self.alphabet)] for byte in digest[:size])
        return f"{self.prefix}mock{body}"


class Account(_Record):
    """A provider account: plan, credit allowance, and billing period."""

    provider: str
    id: str
    plan: str
    credit_limit: Decimal | None
    credits_used: Decimal
    reset_rule: ResetRule
    period_start: datetime
    period_reset: datetime | None
    attributes: dict[str, Any] = Field(default_factory=dict)

    @property
    def remaining(self) -> Decimal | None:
        """Return the unspent allowance, or ``None`` for an unlimited account."""

        if self.credit_limit is None:
            return None
        return max(Decimal(0), self.credit_limit - self.credits_used)


class ApiKey(_Record):
    """One mock API key. The key value is fake and safe to print."""

    provider: str
    key: str
    account_id: str
    label: str
    status: Literal["active", "revoked"]
    scopes: tuple[str, ...] = ()
    credit_limit: Decimal | None = None
    credits_used: Decimal = Decimal(0)
    env_var: str | None = None
    created_at: datetime


class KeylessSetting(_Record):
    """Whether a provider accepts keyless calls, and its keyless call budget."""

    provider: str
    enabled: bool
    per_day: int | None = None
    per_minute: int | None = None


class PriceRule(_Record):
    """Credits and USD that one billed operation unit costs."""

    provider: str
    operation: str
    credits_per_unit: Decimal
    usd_per_unit: Decimal | None = None
    unit: str = "request"
    rule: PricingRule = "per_unit"


class LedgerEntry(_Record):
    """One billed operation."""

    id: int
    ts: datetime
    provider: str
    account_id: str | None
    key_label: str
    operation: str
    units: Decimal
    credits: Decimal
    usd: Decimal | None


class LogEntry(_Record):
    """One request the mock answered (or dropped)."""

    id: int
    ts: datetime
    provider: str
    operation: str
    method: str
    path: str
    key_label: str
    status: int | None
    latency_ms: float
    fault: str | None
    match_key: str | None
    request_summary: dict[str, Any]
    response_body: str | None = None


class Fixture(_Record):
    """A saved response body that replaces synthetic content for one match key."""

    id: int
    provider: str
    operation: str
    match_key: str
    status: int
    body: Any
    created_at: datetime


class AccountSeed(_Record):
    """An account that ``seed`` creates."""

    id: str
    plan: str
    credit_limit: Decimal | None
    reset_rule: ResetRule = "monthly"
    attributes: dict[str, Any] = Field(default_factory=dict)


class KeySeed(_Record):
    """A key that ``seed`` creates; ``key`` is derived from the label when absent."""

    label: str
    account_id: str
    env_var: str | None = None
    scopes: tuple[str, ...] = ()
    credit_limit: Decimal | None = None
    key: str | None = None


class KeylessSeed(_Record):
    """The keyless setting that ``seed`` creates."""

    enabled: bool = True
    per_day: int | None = None
    per_minute: int | None = None


class ProviderSeed(_Record):
    """Default state of one provider."""

    accounts: tuple[AccountSeed, ...] = ()
    keys: tuple[KeySeed, ...] = ()
    keyless: KeylessSeed | None = None
