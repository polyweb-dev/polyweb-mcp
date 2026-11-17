"""SQLite state database: schema creation and short-lived connections.

Every operation opens its own connection, so the CLI, the admin API, and the
request pipeline see each other's writes immediately. WAL mode lets the
server read while the CLI writes.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

__all__ = ["SCHEMA", "TABLES", "Database"]

TABLES = (
    "accounts",
    "api_keys",
    "keyless",
    "pricing",
    "credit_carry",
    "usage_ledger",
    "request_log",
    "fault_rules",
    "fixtures",
    "meta",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    name TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts (
    provider TEXT NOT NULL,
    id TEXT NOT NULL,
    plan TEXT NOT NULL DEFAULT '',
    credit_limit TEXT,
    credits_used TEXT NOT NULL DEFAULT '0',
    reset_rule TEXT NOT NULL DEFAULT 'monthly',
    period_start TEXT NOT NULL,
    period_reset TEXT,
    attributes TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (provider, id)
);
CREATE TABLE IF NOT EXISTS api_keys (
    provider TEXT NOT NULL,
    key TEXT NOT NULL,
    account_id TEXT NOT NULL,
    label TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
    scopes TEXT NOT NULL DEFAULT '[]',
    credit_limit TEXT,
    credits_used TEXT NOT NULL DEFAULT '0',
    env_var TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (provider, key),
    UNIQUE (provider, label),
    FOREIGN KEY (provider, account_id) REFERENCES accounts (provider, id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS keyless (
    provider TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL,
    per_day INTEGER,
    per_minute INTEGER
);
CREATE TABLE IF NOT EXISTS pricing (
    provider TEXT NOT NULL,
    operation TEXT NOT NULL,
    credits_per_unit TEXT NOT NULL,
    usd_per_unit TEXT,
    unit TEXT NOT NULL DEFAULT 'request',
    rule TEXT NOT NULL DEFAULT 'per_unit',
    PRIMARY KEY (provider, operation)
);
CREATE TABLE IF NOT EXISTS credit_carry (
    provider TEXT NOT NULL,
    account_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    carry TEXT NOT NULL,
    PRIMARY KEY (provider, account_id, operation)
);
CREATE TABLE IF NOT EXISTS usage_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    provider TEXT NOT NULL,
    account_id TEXT,
    key_label TEXT NOT NULL,
    operation TEXT NOT NULL,
    units TEXT NOT NULL,
    credits TEXT NOT NULL,
    usd TEXT
);
CREATE INDEX IF NOT EXISTS usage_ledger_scope
    ON usage_ledger (provider, account_id, key_label, ts);
CREATE TABLE IF NOT EXISTS request_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    provider TEXT NOT NULL,
    operation TEXT NOT NULL,
    method TEXT NOT NULL,
    path TEXT NOT NULL,
    key_label TEXT NOT NULL,
    status INTEGER,
    latency_ms REAL NOT NULL,
    fault TEXT,
    match_key TEXT,
    request_summary TEXT NOT NULL,
    response_body TEXT
);
CREATE INDEX IF NOT EXISTS request_log_provider ON request_log (provider, id);
CREATE TABLE IF NOT EXISTS fault_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    operation TEXT NOT NULL,
    kind TEXT NOT NULL,
    params TEXT NOT NULL DEFAULT '{}',
    probability REAL NOT NULL DEFAULT 1.0,
    remaining INTEGER,
    expires_at TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    scenario TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fixtures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    operation TEXT NOT NULL,
    match_key TEXT NOT NULL,
    status INTEGER NOT NULL DEFAULT 200,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (provider, operation, match_key)
);
"""


class Database:
    """One SQLite file; the schema is created when the object is built."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Yield an autocommit connection with foreign keys and a busy timeout."""

        conn = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=10000")
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection inside ``BEGIN IMMEDIATE``; commit or roll back."""

        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
