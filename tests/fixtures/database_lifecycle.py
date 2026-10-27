"""Narrow temporary-database cleanup helper shared by the limit integration suites.

Windows can hold an SQLite file handle briefly after the owning engine is
disposed, so a plain ``unlink`` right after ``close()`` may raise
``PermissionError``.  Callers close their repository first, then remove each
explicit temporary path through :func:`unlink_with_retries`.  Paths are always
passed in by the caller (``tmp_path`` children); the live checkout database is
never inferred.
"""

import gc
import time
from pathlib import Path


def unlink_with_retries(path: Path, *, attempts: int = 20) -> None:
    """Remove a test database after Windows releases delayed SQLite handles."""

    for attempt in range(attempts):
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            gc.collect()
            time.sleep(0.05)
        else:
            return
