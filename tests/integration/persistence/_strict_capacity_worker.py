"""Spawned-process worker for the A4/B6/pool10 strict-capacity acceptance case.

This module is imported by the child interpreter, so it must stay dependency
light: it opens the temporary database, waits on the parent barrier, and tries
``attempts`` strict reservations under the fixed project and pool windows.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from freesearch.models.provider_limits import (
    AuthMode,
    LimitDeniedError,
    LimitOperation,
    LimitStoreUnavailable,
)
from freesearch.persistence.limit_repository import StrictAttemptSpec, StrictWindowSpec
from freesearch.persistence.storage import SQLiteRepository
from tests.fixtures.execution import FIXTURE_ACTOR

_WINDOW_SECONDS = 3600
_POOL_LIMIT = 10
_ATTEMPTS = 4


def run_worker(
    database: str,
    project_id: str,
    credential_id: str,
    binding_id: str,
    project_bucket: str,
    pool_bucket: str,
    project_limit: int,
    project: str,
    barrier: Any,
    results: Any,
    attempts: int = _ATTEMPTS,
) -> None:
    """Reserve this project's allowance in one spawned child process."""

    import asyncio

    async def run() -> dict[str, Any]:
        admitted = 0
        denied = 0
        errors: list[str] = []
        repository = await SQLiteRepository.open(database)
        try:
            spec = StrictAttemptSpec(
                project_id=UUID(project_id),
                credential_id=UUID(credential_id),
                binding_id=UUID(binding_id),
                windows=(
                    StrictWindowSpec(project_bucket, _WINDOW_SECONDS, project_limit),
                    StrictWindowSpec(pool_bucket, _WINDOW_SECONDS, _POOL_LIMIT),
                ),
                # Revision 0002: every capacity row carries the verified actor.
                **FIXTURE_ACTOR,
            )
            barrier.wait(timeout=120)
            for _ in range(attempts):
                try:
                    await repository.limits.reserve_strict(
                        attempt_id=f"proc-{project}-{uuid4().hex}",
                        provider="exa",
                        operation=LimitOperation.SEARCH,
                        auth_mode=AuthMode.KEYED,
                        spec=spec,
                    )
                    admitted += 1
                except LimitDeniedError:
                    denied += 1
                except LimitStoreUnavailable as error:
                    errors.append(f"store unavailable: {error}")
                except Exception as error:  # pragma: no cover - diagnostic path
                    errors.append(f"{type(error).__name__}: {error}")
        except Exception as error:  # pragma: no cover - barrier/open failures
            errors.append(f"{type(error).__name__}: {error}")
        finally:
            await repository.close()
        results.put(
            {
                "project": project,
                "admitted": admitted,
                "denied": denied,
                "errors": errors,
            }
        )

    asyncio.run(run())
