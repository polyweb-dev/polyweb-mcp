"""Fixed rate-limit windows kept in the mock's ``meta`` table.

A private helper of the Keenable and Tinyfish plugins (discovery skips modules
whose name starts with ``_``). The core keyless budget counts ledger rows per
provider; these providers need per-endpoint and per-account windows with their
own reset instants, which the core does not model. Each named window stores
its start and its used units, so counters survive a restart and ``seed
--reset`` / ``reset`` clear them.

A window is either *anchored* (it starts at the first request after the
previous window ended, as Keenable's public hourly pool does) or *aligned*
(it starts at a multiple of its length since the Unix epoch, as a per-minute
counter with a known reset second does).
"""

import json
import math
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from polyweb_provider_mock.store import MockStore

__all__ = ["Window", "WindowSpec", "add", "admit", "peek"]


@dataclass(frozen=True)
class WindowSpec:
    """One counter: a unique ``name``, its ``limit``, and its length in seconds."""

    name: str
    limit: int
    seconds: float
    aligned: bool = False


@dataclass(frozen=True)
class Window:
    """The state of one counter after a check."""

    spec: WindowSpec
    used: int
    start: datetime

    @property
    def reset(self) -> datetime:
        return self.start + timedelta(seconds=self.spec.seconds)

    @property
    def remaining(self) -> int:
        return max(0, self.spec.limit - self.used)

    def retry_after(self, now: datetime) -> int:
        """Return whole seconds until the window resets, at least 1."""

        return max(1, math.ceil((self.reset - now).total_seconds()))


def _start(spec: WindowSpec, now: datetime) -> datetime:
    if not spec.aligned:
        return now
    stamp = math.floor(now.timestamp() / spec.seconds) * spec.seconds
    return datetime.fromtimestamp(stamp, UTC)


def _read(conn: sqlite3.Connection, spec: WindowSpec, now: datetime) -> Window:
    row = conn.execute("SELECT value FROM meta WHERE name = ?", (f"window:{spec.name}",)).fetchone()
    if row is not None:
        data = json.loads(row["value"])
        window = Window(spec, int(data["used"]), datetime.fromisoformat(data["start"]))
        if now < window.reset:
            return window
    return Window(spec, 0, _start(spec, now))


def _write(conn: sqlite3.Connection, window: Window) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO meta (name, value) VALUES (?, ?)",
        (
            f"window:{window.spec.name}",
            json.dumps({"start": window.start.isoformat(), "used": window.used}),
        ),
    )


def admit(
    store: MockStore, specs: Sequence[WindowSpec], units: int = 1
) -> tuple[Window | None, list[Window]]:
    """Consume ``units`` in every window, or in none when one would overflow.

    Returns the first window that refused (or ``None``) and the state of every
    window after the check, in ``specs`` order.
    """

    now = store.now()
    with store.db.transaction() as conn:
        windows = [_read(conn, spec, now) for spec in specs]
        refused = next((w for w in windows if w.used + units > w.spec.limit), None)
        if refused is None:
            windows = [Window(w.spec, w.used + units, w.start) for w in windows]
        for window in windows:
            _write(conn, window)
    return refused, windows


def peek(store: MockStore, spec: WindowSpec) -> Window:
    """Return a window's state without consuming it."""

    with store.db.connect() as conn:
        return _read(conn, spec, store.now())


def add(store: MockStore, spec: WindowSpec, units: int) -> Window:
    """Count ``units`` in a window even past its limit (for example successes)."""

    now = store.now()
    with store.db.transaction() as conn:
        current = _read(conn, spec, now)
        window = Window(spec, current.used + units, current.start)
        _write(conn, window)
    return window
