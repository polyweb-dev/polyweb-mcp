"""The mock's service layer: every state read and write goes through :class:`MockStore`.

The admin CLI, the admin API, and the request pipeline share this class, so
a CLI change applies to the next request without a restart. Credit amounts
are stored as decimal strings and handled as :class:`~decimal.Decimal`.
"""

import json
import random
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from polyweb_provider_mock.db import TABLES, Database
from polyweb_provider_mock.faults import (
    FaultKind,
    FaultParams,
    FaultPlan,
    FaultRule,
    FaultSpec,
)
from polyweb_provider_mock.models import (
    Account,
    ApiKey,
    Fixture,
    KeyFormat,
    KeylessSetting,
    LedgerEntry,
    LogEntry,
    PriceRule,
    ResetRule,
)

if TYPE_CHECKING:
    from polyweb_provider_mock.providers.base import ProviderPlugin

__all__ = ["Charge", "MockStore", "NotFoundError", "Principal", "QuotaExhausted"]

_LOG_RETENTION = 10_000
_UNSET: Any = object()


class NotFoundError(LookupError):
    """A named account, key, rule, fixture, or log entry does not exist."""


class QuotaExhausted(Exception):
    """A billed operation exceeds the account or key allowance."""

    def __init__(self, scope: Literal["account", "key"]) -> None:
        super().__init__(f"{scope} credits exhausted")
        self.scope = scope


@dataclass(frozen=True)
class Principal:
    """Who a request runs as: a mock key and its account, or the keyless rail."""

    provider: str
    key: ApiKey | None = None
    account: Account | None = None
    keyless: bool = False

    @property
    def label(self) -> str:
        if self.key is not None:
            return self.key.label
        return "keyless" if self.keyless else "anonymous"


@dataclass(frozen=True)
class Charge:
    """What one billed operation debited and reports."""

    operation: str
    units: Decimal
    credits: Decimal
    usd: Decimal | None


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _dec(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _text(value: Decimal | None) -> str | None:
    return None if value is None else format(value.normalize(), "f")


def _ts(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat()


def _dt(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def period_start(rule: ResetRule, now: datetime) -> datetime:
    """Return the start of the billing period that contains ``now``."""

    day = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    if rule == "monthly":
        return day.replace(day=1)
    return day if rule == "daily" else now


def next_reset(rule: ResetRule, start: datetime) -> datetime | None:
    """Return when a period that began at ``start`` ends; ``None`` never resets."""

    if rule == "daily":
        return start + timedelta(days=1)
    if rule == "monthly":
        year, month = (start.year + 1, 1) if start.month == 12 else (start.year, start.month + 1)
        return start.replace(year=year, month=month, day=1)
    return None


def _account(row: sqlite3.Row) -> Account:
    return Account(
        provider=row["provider"],
        id=row["id"],
        plan=row["plan"],
        credit_limit=_dec(row["credit_limit"]),
        credits_used=Decimal(row["credits_used"]),
        reset_rule=row["reset_rule"],
        period_start=datetime.fromisoformat(row["period_start"]),
        period_reset=_dt(row["period_reset"]),
        attributes=json.loads(row["attributes"]),
    )


def _api_key(row: sqlite3.Row) -> ApiKey:
    return ApiKey(
        provider=row["provider"],
        key=row["key"],
        account_id=row["account_id"],
        label=row["label"],
        status=row["status"],
        scopes=tuple(json.loads(row["scopes"])),
        credit_limit=_dec(row["credit_limit"]),
        credits_used=Decimal(row["credits_used"]),
        env_var=row["env_var"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _price(row: sqlite3.Row) -> PriceRule:
    return PriceRule(
        provider=row["provider"],
        operation=row["operation"],
        credits_per_unit=Decimal(row["credits_per_unit"]),
        usd_per_unit=_dec(row["usd_per_unit"]),
        unit=row["unit"],
        rule=row["rule"],
    )


def _fault(row: sqlite3.Row) -> FaultRule:
    return FaultRule(
        id=row["id"],
        provider=row["provider"],
        operation=row["operation"],
        kind=FaultKind(row["kind"]),
        params=FaultParams.model_validate_json(row["params"]),
        probability=row["probability"],
        remaining=row["remaining"],
        expires_at=_dt(row["expires_at"]),
        enabled=bool(row["enabled"]),
        scenario=row["scenario"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _fixture(row: sqlite3.Row) -> Fixture:
    return Fixture(
        id=row["id"],
        provider=row["provider"],
        operation=row["operation"],
        match_key=row["match_key"],
        status=row["status"],
        body=json.loads(row["body"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _log(row: sqlite3.Row, *, with_body: bool) -> LogEntry:
    return LogEntry(
        id=row["id"],
        ts=datetime.fromisoformat(row["ts"]),
        provider=row["provider"],
        operation=row["operation"],
        method=row["method"],
        path=row["path"],
        key_label=row["key_label"],
        status=row["status"],
        latency_ms=row["latency_ms"],
        fault=row["fault"],
        match_key=row["match_key"],
        request_summary=json.loads(row["request_summary"]),
        response_body=row["response_body"] if with_body else None,
    )


class MockStore:
    """State access for accounts, keys, pricing, billing, faults, fixtures, and logs."""

    def __init__(self, db: Database | Path, *, now: Callable[[], datetime] = _utcnow) -> None:
        self.db = db if isinstance(db, Database) else Database(db)
        self.now = now

    # ------------------------------------------------------------ lifecycle

    def is_seeded(self) -> bool:
        with self.db.connect() as conn:
            return (
                conn.execute("SELECT 1 FROM meta WHERE name = 'seeded_at'").fetchone() is not None
            )

    def reset(self) -> None:
        """Delete all state: accounts, keys, pricing, ledger, log, faults, fixtures."""

        with self.db.transaction() as conn:
            for table in TABLES:
                conn.execute(f"DELETE FROM {table}")

    def seed(self, plugins: Iterable["ProviderPlugin"], *, reset: bool = False) -> dict[str, int]:
        """Create each plugin's default accounts, keys, keyless setting, and prices.

        Existing rows are kept, so a second seed is a no-op. ``reset`` first
        deletes all state. Returns the number of keys per provider.
        """

        if reset:
            self.reset()
        now = self.now()
        created: dict[str, int] = {}
        with self.db.transaction() as conn:
            for plugin in plugins:
                created[plugin.name] = self._seed_provider(conn, plugin, now)
            conn.execute(
                "INSERT OR REPLACE INTO meta (name, value) VALUES ('seeded_at', ?)", (_ts(now),)
            )
        return created

    def _seed_provider(
        self, conn: sqlite3.Connection, plugin: "ProviderPlugin", now: datetime
    ) -> int:
        seed = plugin.default_seed()
        for account in seed.accounts:
            start = period_start(account.reset_rule, now)
            conn.execute(
                "INSERT OR IGNORE INTO accounts (provider, id, plan, credit_limit, reset_rule,"
                " period_start, period_reset, attributes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    plugin.name,
                    account.id,
                    account.plan,
                    _text(account.credit_limit),
                    account.reset_rule,
                    _ts(start),
                    _ts(next_reset(account.reset_rule, start)),
                    json.dumps(account.attributes),
                ),
            )
        for key in seed.keys:
            value = key.key or plugin.key_format.generate(f"{plugin.name}:{key.label}")
            conn.execute(
                "INSERT OR IGNORE INTO api_keys (provider, key, account_id, label, scopes,"
                " credit_limit, env_var, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    plugin.name,
                    value,
                    key.account_id,
                    key.label,
                    json.dumps(list(key.scopes)),
                    _text(key.credit_limit),
                    key.env_var,
                    _ts(now),
                ),
            )
        if seed.keyless is not None:
            conn.execute(
                "INSERT OR IGNORE INTO keyless (provider, enabled, per_day, per_minute)"
                " VALUES (?, ?, ?, ?)",
                (
                    plugin.name,
                    int(seed.keyless.enabled),
                    seed.keyless.per_day,
                    seed.keyless.per_minute,
                ),
            )
        for price in plugin.default_pricing():
            self._upsert_price(conn, price, replace=False)
        return len(seed.keys)

    def next_sequence(self, name: str) -> int:
        """Return the next value of a named counter (1, 2, 3, ...)."""

        with self.db.transaction() as conn:
            row = conn.execute(
                "INSERT INTO meta (name, value) VALUES (?, '1') ON CONFLICT (name)"
                " DO UPDATE SET value = CAST(value AS INTEGER) + 1 RETURNING value",
                (f"seq:{name}",),
            ).fetchone()
        return int(row["value"])

    # ------------------------------------------------------------- accounts

    def _rolled(self, conn: sqlite3.Connection, provider: str, account_id: str) -> Account:
        """Read an account, first starting any billing periods that have begun."""

        row = conn.execute(
            "SELECT * FROM accounts WHERE provider = ? AND id = ?", (provider, account_id)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no {provider} account {account_id!r}")
        account = _account(row)
        now = self.now()
        start, reset = account.period_start, account.period_reset
        if reset is None or now < reset:
            return account
        while reset is not None and now >= reset:
            start, reset = reset, next_reset(account.reset_rule, reset)
        conn.execute(
            "UPDATE accounts SET credits_used = '0', period_start = ?, period_reset = ?"
            " WHERE provider = ? AND id = ?",
            (_ts(start), _ts(reset), provider, account_id),
        )
        conn.execute(
            "UPDATE api_keys SET credits_used = '0' WHERE provider = ? AND account_id = ?",
            (provider, account_id),
        )
        conn.execute(
            "DELETE FROM credit_carry WHERE provider = ? AND account_id = ?",
            (provider, account_id),
        )
        return account.model_copy(
            update={"credits_used": Decimal(0), "period_start": start, "period_reset": reset}
        )

    def _account_id(self, conn: sqlite3.Connection, provider: str, account_id: str | None) -> str:
        if account_id is not None:
            return account_id
        row = conn.execute(
            "SELECT id FROM accounts WHERE provider = ? ORDER BY rowid LIMIT 1", (provider,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no {provider} account; run `polyweb-mock seed`")
        return str(row["id"])

    def accounts(self, provider: str | None = None) -> list[Account]:
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT provider, id FROM accounts WHERE ? IS NULL OR provider = ?"
                " ORDER BY provider, rowid",
                (provider, provider),
            ).fetchall()
            return [self._rolled(conn, row["provider"], row["id"]) for row in rows]

    def account(self, provider: str, account_id: str | None = None) -> Account:
        """Return one account; the provider's first account by default."""

        with self.db.transaction() as conn:
            return self._rolled(conn, provider, self._account_id(conn, provider, account_id))

    def add_credits(self, provider: str, amount: Decimal, account_id: str | None = None) -> Account:
        """Raise the account allowance by ``amount`` credits."""

        with self.db.transaction() as conn:
            current = self._rolled(conn, provider, self._account_id(conn, provider, account_id))
            if current.credit_limit is None:
                raise ValueError("the account is unlimited; use `credits set` to give it a limit")
            conn.execute(
                "UPDATE accounts SET credit_limit = ? WHERE provider = ? AND id = ?",
                (_text(current.credit_limit + amount), provider, current.id),
            )
            return self._rolled(conn, provider, current.id)

    def set_credits(
        self,
        provider: str,
        balance: Decimal | None,
        account_id: str | None = None,
        *,
        used: Decimal | None = None,
    ) -> Account:
        """Set the remaining balance (``None`` = unlimited) and optionally the used credits."""

        with self.db.transaction() as conn:
            current = self._rolled(conn, provider, self._account_id(conn, provider, account_id))
            spent = current.credits_used if used is None else used
            limit = None if balance is None else spent + balance
            conn.execute(
                "UPDATE accounts SET credit_limit = ?, credits_used = ?"
                " WHERE provider = ? AND id = ?",
                (_text(limit), _text(spent), provider, current.id),
            )
            return self._rolled(conn, provider, current.id)

    def set_plan(self, provider: str, plan: str, account_id: str | None = None) -> Account:
        with self.db.transaction() as conn:
            account_id = self._account_id(conn, provider, account_id)
            conn.execute(
                "UPDATE accounts SET plan = ? WHERE provider = ? AND id = ?",
                (plan, provider, account_id),
            )
            return self._rolled(conn, provider, account_id)

    # ----------------------------------------------------------------- keys

    def keys(self, provider: str | None = None) -> list[ApiKey]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM api_keys WHERE ? IS NULL OR provider = ? ORDER BY provider, rowid",
                (provider, provider),
            ).fetchall()
        return [_api_key(row) for row in rows]

    def create_key(
        self,
        provider: str,
        key_format: KeyFormat,
        *,
        account_id: str | None = None,
        label: str | None = None,
        key: str | None = None,
        scopes: Sequence[str] = (),
        env_var: str | None = None,
        credit_limit: Decimal | None = None,
    ) -> ApiKey:
        """Create an active key on an account; the value is random unless given."""

        value = key or key_format.generate()
        with self.db.transaction() as conn:
            account_id = self._account_id(conn, provider, account_id)
            self._rolled(conn, provider, account_id)
            label = label or f"key-{value[-6:]}"
            try:
                conn.execute(
                    "INSERT INTO api_keys (provider, key, account_id, label, scopes,"
                    " credit_limit, env_var, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        provider,
                        value,
                        account_id,
                        label,
                        json.dumps(list(scopes)),
                        _text(credit_limit),
                        env_var,
                        _ts(self.now()),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"a {provider} key with that value or label exists") from exc
            row = conn.execute(
                "SELECT * FROM api_keys WHERE provider = ? AND key = ?", (provider, value)
            ).fetchone()
        return _api_key(row)

    def set_key_status(
        self, provider: str, key_or_label: str, status: Literal["active", "revoked"]
    ) -> ApiKey:
        """Revoke (or restore) a key named by its value or its label."""

        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM api_keys WHERE provider = ? AND (key = ? OR label = ?)",
                (provider, key_or_label, key_or_label),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"no {provider} key {key_or_label!r}")
            conn.execute(
                "UPDATE api_keys SET status = ? WHERE provider = ? AND key = ?",
                (status, provider, row["key"]),
            )
        return _api_key(row).model_copy(update={"status": status})

    def resolve(self, provider: str, presented: str) -> Principal | None:
        """Return the principal of a presented key value, or ``None`` when unknown."""

        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM api_keys WHERE provider = ? AND key = ?", (provider, presented)
            ).fetchone()
            if row is None:
                return None
            account = self._rolled(conn, provider, row["account_id"])
            key = conn.execute(
                "SELECT * FROM api_keys WHERE provider = ? AND key = ?", (provider, presented)
            ).fetchone()
        return Principal(provider=provider, key=_api_key(key), account=account)

    def export_keys(self) -> list[tuple[str, str]]:
        """Return ``(env_var, key)`` for every active key that names a variable."""

        exported: dict[str, str] = {}
        for key in self.keys():
            if key.env_var and key.status == "active":
                exported.setdefault(key.env_var, key.key)
        return sorted(exported.items())

    # -------------------------------------------------------------- keyless

    def keyless(self, provider: str) -> KeylessSetting | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM keyless WHERE provider = ?", (provider,)).fetchone()
        if row is None:
            return None
        return KeylessSetting(
            provider=provider,
            enabled=bool(row["enabled"]),
            per_day=row["per_day"],
            per_minute=row["per_minute"],
        )

    def keyless_settings(self) -> list[KeylessSetting]:
        with self.db.connect() as conn:
            names = [row["provider"] for row in conn.execute("SELECT provider FROM keyless")]
        return [setting for name in sorted(names) if (setting := self.keyless(name)) is not None]

    def set_keyless(
        self,
        provider: str,
        *,
        enabled: bool | None = None,
        per_day: int | None = _UNSET,
        per_minute: int | None = _UNSET,
    ) -> KeylessSetting:
        """Change the keyless setting; omitted arguments keep their current value."""

        current = self.keyless(provider) or KeylessSetting(provider=provider, enabled=False)
        updated = current.model_copy(
            update={
                "enabled": current.enabled if enabled is None else enabled,
                "per_day": current.per_day if per_day is _UNSET else per_day,
                "per_minute": current.per_minute if per_minute is _UNSET else per_minute,
            }
        )
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO keyless (provider, enabled, per_day, per_minute)"
                " VALUES (?, ?, ?, ?)",
                (provider, int(updated.enabled), updated.per_day, updated.per_minute),
            )
        return updated

    def keyless_retry_after(self, provider: str) -> tuple[str, int] | None:
        """Return ``(window, seconds)`` when the keyless budget is spent, else ``None``.

        The day window is the UTC calendar day; the minute window is rolling.
        """

        setting = self.keyless(provider)
        if setting is None:
            return None
        now = self.now()
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        minute = now - timedelta(minutes=1)
        with self.db.connect() as conn:

            def calls_since(since: datetime) -> list[str]:
                rows = conn.execute(
                    "SELECT ts FROM usage_ledger WHERE provider = ? AND account_id IS NULL"
                    " AND key_label = 'keyless' AND ts >= ? ORDER BY ts",
                    (provider, _ts(since)),
                ).fetchall()
                return [row["ts"] for row in rows]

            if setting.per_minute is not None:
                recent = calls_since(minute)
                if len(recent) >= setting.per_minute:
                    oldest = datetime.fromisoformat(recent[0])
                    return "minute", max(1, int((oldest - minute).total_seconds()) + 1)
            if setting.per_day is not None and len(calls_since(day)) >= setting.per_day:
                return "day", max(1, int((day + timedelta(days=1) - now).total_seconds()))
        return None

    # -------------------------------------------------------------- pricing

    def prices(self, provider: str | None = None) -> list[PriceRule]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pricing WHERE ? IS NULL OR provider = ?"
                " ORDER BY provider, operation",
                (provider, provider),
            ).fetchall()
        return [_price(row) for row in rows]

    def price(self, provider: str, operation: str) -> PriceRule | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM pricing WHERE provider = ? AND operation = ?", (provider, operation)
            ).fetchone()
        return None if row is None else _price(row)

    def set_price(self, rule: PriceRule) -> PriceRule:
        with self.db.transaction() as conn:
            self._upsert_price(conn, rule, replace=True)
        return rule

    @staticmethod
    def _upsert_price(conn: sqlite3.Connection, rule: PriceRule, *, replace: bool) -> None:
        verb = "INSERT OR REPLACE" if replace else "INSERT OR IGNORE"
        conn.execute(
            f"{verb} INTO pricing (provider, operation, credits_per_unit, usd_per_unit, unit, rule)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                rule.provider,
                rule.operation,
                _text(rule.credits_per_unit),
                _text(rule.usd_per_unit),
                rule.unit,
                rule.rule,
            ),
        )

    # -------------------------------------------------------------- billing

    def charge(self, principal: Principal, operation: str, units: Decimal = Decimal(1)) -> Charge:
        """Debit one billed operation and record it in the ledger.

        The debit follows the operation's price rule; an operation without a
        price costs nothing. A keyed principal needs funds on both its account
        and its key, otherwise :class:`QuotaExhausted` is raised and nothing
        is debited. Keyless calls are recorded but debit no account.
        """

        rule = self.price(principal.provider, operation)
        amount = Decimal(0) if rule is None else rule.credits_per_unit * units
        usd = None if rule is None or rule.usd_per_unit is None else rule.usd_per_unit * units
        with self.db.transaction() as conn:
            account_id: str | None = None
            debit = amount
            if principal.account is not None and not principal.keyless:
                account = self._rolled(conn, principal.provider, principal.account.id)
                account_id = account.id
                if rule is not None and rule.rule == "accumulate":
                    debit = self._accumulate(conn, account, operation, amount)
                self._check_funds(conn, account, principal.key, debit)
                self._debit(conn, account, principal.key, debit)
            elif rule is not None and rule.rule == "accumulate":
                debit = amount.to_integral_value(rounding=ROUND_FLOOR)
            conn.execute(
                "INSERT INTO usage_ledger (ts, provider, account_id, key_label, operation,"
                " units, credits, usd) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _ts(self.now()),
                    principal.provider,
                    account_id,
                    principal.label,
                    operation,
                    _text(units),
                    _text(debit),
                    _text(usd),
                ),
            )
        return Charge(operation=operation, units=units, credits=debit, usd=usd)

    def _accumulate(
        self, conn: sqlite3.Connection, account: Account, operation: str, amount: Decimal
    ) -> Decimal:
        row = conn.execute(
            "SELECT carry FROM credit_carry"
            " WHERE provider = ? AND account_id = ? AND operation = ?",
            (account.provider, account.id, operation),
        ).fetchone()
        total = (Decimal(row["carry"]) if row else Decimal(0)) + amount
        debit = total.to_integral_value(rounding=ROUND_FLOOR)
        conn.execute(
            "INSERT OR REPLACE INTO credit_carry (provider, account_id, operation, carry)"
            " VALUES (?, ?, ?, ?)",
            (account.provider, account.id, operation, _text(total - debit)),
        )
        return debit

    @staticmethod
    def _check_funds(
        conn: sqlite3.Connection, account: Account, key: ApiKey | None, debit: Decimal
    ) -> None:
        if account.credit_limit is not None:
            left = account.credit_limit - account.credits_used
            if left <= 0 or debit > left:
                raise QuotaExhausted("account")
        if key is None:
            return
        row = conn.execute(
            "SELECT credit_limit, credits_used FROM api_keys WHERE provider = ? AND key = ?",
            (key.provider, key.key),
        ).fetchone()
        limit = _dec(row["credit_limit"]) if row else None
        if limit is not None:
            left = limit - Decimal(row["credits_used"])
            if left <= 0 or debit > left:
                raise QuotaExhausted("key")

    @staticmethod
    def _debit(
        conn: sqlite3.Connection, account: Account, key: ApiKey | None, debit: Decimal
    ) -> None:
        if not debit:
            return
        conn.execute(
            "UPDATE accounts SET credits_used = ? WHERE provider = ? AND id = ?",
            (_text(account.credits_used + debit), account.provider, account.id),
        )
        if key is not None:
            row = conn.execute(
                "SELECT credits_used FROM api_keys WHERE provider = ? AND key = ?",
                (key.provider, key.key),
            ).fetchone()
            conn.execute(
                "UPDATE api_keys SET credits_used = ? WHERE provider = ? AND key = ?",
                (_text(Decimal(row["credits_used"]) + debit), key.provider, key.key),
            )

    def usage_by_operation(
        self,
        provider: str,
        *,
        account_id: str | None = None,
        key_label: str | None = None,
        since: datetime | None = None,
    ) -> dict[str, Decimal]:
        """Sum ledger credits per operation, optionally for one account, key, or period."""

        totals: dict[str, Decimal] = {}
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT operation, credits FROM usage_ledger WHERE provider = ?"
                " AND (? IS NULL OR account_id = ?) AND (? IS NULL OR key_label = ?)"
                " AND (? IS NULL OR ts >= ?)",
                (
                    provider,
                    account_id,
                    account_id,
                    key_label,
                    key_label,
                    _ts(since),
                    _ts(since),
                ),
            ).fetchall()
        for row in rows:
            totals[row["operation"]] = totals.get(row["operation"], Decimal(0)) + Decimal(
                row["credits"]
            )
        return totals

    def ledger(self, provider: str | None = None, limit: int = 50) -> list[LedgerEntry]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM usage_ledger WHERE ? IS NULL OR provider = ?"
                " ORDER BY id DESC LIMIT ?",
                (provider, provider, limit),
            ).fetchall()
        return [
            LedgerEntry(
                id=row["id"],
                ts=datetime.fromisoformat(row["ts"]),
                provider=row["provider"],
                account_id=row["account_id"],
                key_label=row["key_label"],
                operation=row["operation"],
                units=Decimal(row["units"]),
                credits=Decimal(row["credits"]),
                usd=_dec(row["usd"]),
            )
            for row in reversed(rows)
        ]

    # --------------------------------------------------------------- faults

    def faults(self) -> list[FaultRule]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM fault_rules ORDER BY id").fetchall()
        return [_fault(row) for row in rows]

    def add_fault(self, spec: FaultSpec) -> FaultRule:
        now = self.now()
        expires = (
            None
            if spec.duration_seconds is None
            else now + timedelta(seconds=spec.duration_seconds)
        )
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO fault_rules (provider, operation, kind, params, probability,"
                " remaining, expires_at, enabled, scenario, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    spec.provider,
                    spec.operation,
                    spec.kind.value,
                    spec.params.model_dump_json(exclude_defaults=True),
                    spec.probability,
                    spec.count,
                    _ts(expires),
                    int(spec.enabled),
                    spec.scenario,
                    _ts(now),
                ),
            )
            row = conn.execute(
                "SELECT * FROM fault_rules WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return _fault(row)

    def clear_faults(
        self,
        *,
        rule_id: int | None = None,
        provider: str | None = None,
        scenario: str | None = None,
        kind: FaultKind | None = None,
    ) -> int:
        """Delete matching rules (all rules without filters); return how many."""

        with self.db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM fault_rules WHERE (? IS NULL OR id = ?)"
                " AND (? IS NULL OR provider = ?)"
                " AND (? IS NULL OR scenario = ?) AND (? IS NULL OR kind = ?)",
                (
                    rule_id,
                    rule_id,
                    provider,
                    provider,
                    scenario,
                    scenario,
                    kind,
                    kind,
                ),
            )
        return cursor.rowcount

    def set_fault_enabled(self, rule_id: int, enabled: bool) -> FaultRule:
        with self.db.transaction() as conn:
            conn.execute("UPDATE fault_rules SET enabled = ? WHERE id = ?", (int(enabled), rule_id))
            row = conn.execute("SELECT * FROM fault_rules WHERE id = ?", (rule_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"no fault rule {rule_id}")
        return _fault(row)

    def set_latency(
        self, provider: str, ms: float, jitter_ms: float = 0.0, *, operation: str = "*"
    ) -> FaultRule | None:
        """Replace the standing latency of a provider (and operation); 0 ms removes it."""

        tag = f"latency:{provider}:{operation}"
        self.clear_faults(scenario=tag)
        if ms <= 0 and jitter_ms <= 0:
            return None
        return self.add_fault(
            FaultSpec(
                provider=provider,
                operation=operation,
                kind=FaultKind.LATENCY,
                params=FaultParams(ms=ms, jitter_ms=jitter_ms),
                scenario=tag,
            )
        )

    def draw_faults(
        self, provider: str, operation: str, *, billable: bool, rng: random.Random
    ) -> FaultPlan:
        """Roll the matching rules for one request and spend their counts.

        Every firing latency rule adds delay. The first firing rule of another
        kind becomes the outcome, and later non-latency rules are not rolled.
        ``quota_exhausted`` rules apply to billed operations only.
        """

        now = self.now()
        delay = 0.0
        action: FaultRule | None = None
        fired: list[str] = []
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM fault_rules WHERE enabled = 1 AND provider IN (?, '*')"
                " AND operation IN (?, '*') ORDER BY id",
                (provider, operation),
            ).fetchall()
            for rule in map(_fault, rows):
                latency = rule.kind is FaultKind.LATENCY
                if not rule.active(now) or (action is not None and not latency):
                    continue
                if rule.kind is FaultKind.QUOTA_EXHAUSTED and not billable:
                    continue
                if rng.random() >= rule.probability:
                    continue
                if rule.remaining is not None:
                    conn.execute(
                        "UPDATE fault_rules SET remaining = remaining - 1,"
                        " enabled = CASE WHEN remaining <= 1 THEN 0 ELSE enabled END WHERE id = ?",
                        (rule.id,),
                    )
                fired.append(rule.label)
                if latency:
                    ms = rule.params.ms or 0.0
                    delay += (ms + rng.uniform(0.0, rule.params.jitter_ms or 0.0)) / 1000.0
                else:
                    action = rule
        return FaultPlan(delay_seconds=delay, action=action, fired=tuple(fired))

    # ------------------------------------------------------------- fixtures

    def fixtures(self, provider: str | None = None) -> list[Fixture]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM fixtures WHERE ? IS NULL OR provider = ?"
                " ORDER BY provider, operation, match_key",
                (provider, provider),
            ).fetchall()
        return [_fixture(row) for row in rows]

    def fixture(self, provider: str, operation: str, match_key: str) -> Fixture | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM fixtures WHERE provider = ? AND operation = ? AND match_key = ?",
                (provider, operation, match_key),
            ).fetchone()
        return None if row is None else _fixture(row)

    def save_fixture(
        self, provider: str, operation: str, match_key: str, body: Any, *, status: int = 200
    ) -> Fixture:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO fixtures (provider, operation, match_key, status, body, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (provider, operation, match_key)"
                " DO UPDATE SET status = excluded.status, body = excluded.body,"
                " created_at = excluded.created_at",
                (provider, operation, match_key, status, json.dumps(body), _ts(self.now())),
            )
            row = conn.execute(
                "SELECT * FROM fixtures WHERE provider = ? AND operation = ? AND match_key = ?",
                (provider, operation, match_key),
            ).fetchone()
        return _fixture(row)

    def save_fixture_from_log(self, log_id: int, *, match_key: str | None = None) -> Fixture:
        """Save the JSON response of a logged request as a fixture."""

        entry = self.log_entry(log_id)
        if entry is None or entry.response_body is None:
            raise NotFoundError(f"no logged response {log_id}")
        key = match_key or entry.match_key
        if key is None:
            raise ValueError("the logged request has no match key; pass one explicitly")
        try:
            body = json.loads(entry.response_body)
        except json.JSONDecodeError as exc:
            raise ValueError("the logged response is not JSON") from exc
        return self.save_fixture(
            entry.provider, entry.operation, key, body, status=entry.status or 200
        )

    def delete_fixture(self, fixture_id: int) -> bool:
        with self.db.transaction() as conn:
            cursor = conn.execute("DELETE FROM fixtures WHERE id = ?", (fixture_id,))
        return cursor.rowcount > 0

    # ------------------------------------------------------------------ log

    def log_request(
        self,
        *,
        provider: str,
        operation: str,
        method: str,
        path: str,
        key_label: str,
        status: int | None,
        latency_ms: float,
        fault: str | None,
        match_key: str | None,
        summary: dict[str, Any],
        response_body: str | None,
    ) -> int:
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO request_log (ts, provider, operation, method, path, key_label,"
                " status, latency_ms, fault, match_key, request_summary, response_body)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _ts(self.now()),
                    provider,
                    operation,
                    method,
                    path,
                    key_label,
                    status,
                    round(latency_ms, 2),
                    fault,
                    match_key,
                    json.dumps(summary),
                    response_body,
                ),
            )
            log_id = int(cursor.lastrowid or 0)
            if log_id % 100 == 0:
                conn.execute("DELETE FROM request_log WHERE id <= ?", (log_id - _LOG_RETENTION,))
        return log_id

    def log_tail(
        self, provider: str | None = None, limit: int = 20, *, with_bodies: bool = False
    ) -> list[LogEntry]:
        """Return the latest requests, oldest first."""

        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM request_log WHERE ? IS NULL OR provider = ?"
                " ORDER BY id DESC LIMIT ?",
                (provider, provider, limit),
            ).fetchall()
        return [_log(row, with_body=with_bodies) for row in reversed(rows)]

    def log_entry(self, log_id: int) -> LogEntry | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM request_log WHERE id = ?", (log_id,)).fetchone()
        return None if row is None else _log(row, with_body=True)
