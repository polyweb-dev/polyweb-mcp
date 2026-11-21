"""Fixed rate-limit windows with their own reset instants, kept in the ``meta`` table.

The core keyless budget counts ledger rows per provider. A plugin that needs
per-endpoint or per-account counters with their own reset times declares
:class:`WindowSpec` values and spends them through
:meth:`~polyweb_provider_mock.providers.base.OperationContext.admit` (or the
matching :class:`~polyweb_provider_mock.store.MockStore` methods). Each named
window stores its start and its used units, so counters survive a restart and
``seed --reset`` / ``reset`` clear them.

A window is either *anchored* (it starts at the first request after the
previous window ended, as Keenable's public hourly pool does) or *aligned*
(it starts at a multiple of its length since the Unix epoch, as a per-minute
counter with a known reset second does).
"""

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

__all__ = ["Window", "WindowSpec", "read_window", "write_window"]


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


def read_window(conn: sqlite3.Connection, spec: WindowSpec, now: datetime) -> Window:
    """Return the current window; a window that has ended starts again empty."""

    row = conn.execute("SELECT value FROM meta WHERE name = ?", (f"window:{spec.name}",)).fetchone()
    if row is not None:
        data = json.loads(row["value"])
        window = Window(spec, int(data["used"]), datetime.fromisoformat(data["start"]))
        if now < window.reset:
            return window
    return Window(spec, 0, _start(spec, now))


def write_window(conn: sqlite3.Connection, window: Window) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO meta (name, value) VALUES (?, ?)",
        (
            f"window:{window.spec.name}",
            json.dumps({"start": window.start.isoformat(), "used": window.used}),
        ),
    )
