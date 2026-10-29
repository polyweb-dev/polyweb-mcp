"""Spawned worker for native catalog window serialization; fake/temp DB only."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from freesearch.models.provider_limits import (
    AuthMode,
    LimitAdmission,
    LimitDeniedError,
    LimitOperation,
    ProviderLimitRecord,
    RateBlock,
    RateReservation,
    RateScope,
    RateWindow,
    RateWindowName,
)
from freesearch.persistence.storage import SQLiteRepository
from tests.fixtures.execution import FIXTURE_ACTOR


def run_worker(database, provider, api, barrier, results):
    async def run():
        repository = await SQLiteRepository.open(database)
        try:
            now = datetime.now(UTC)
            record = ProviderLimitRecord(
                provider=provider,
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                supported=True,
                transport_available=True,
                rate=RateBlock(
                    windows=[
                        RateWindow(
                            bucket_id="shared-native",
                            limit=Decimal("1"),
                            scope=RateScope.KEY,
                            window=RateWindowName.HOUR,
                        )
                    ]
                ),
            )
            admission = LimitAdmission(
                provider=provider,
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                attempt_id=uuid4().hex,
                created_at=now,
                expires_at=now + timedelta(minutes=5),
                rate_reservations=[
                    RateReservation(bucket_id="shared-native", window=RateWindowName.HOUR)
                ],
                **FIXTURE_ACTOR,
            )
            barrier.wait(timeout=120)
            try:
                if api == "reserve":
                    await repository.limits.reserve(admission, record=record)
                else:
                    await repository.limits.reserve_attempt(
                        attempt_id=admission.attempt_id,
                        provider=provider,
                        operation=admission.operation,
                        auth_mode=admission.auth_mode,
                        admission=admission,
                        record=record,
                    )
                results.put("admitted")
            except LimitDeniedError:
                results.put("denied")
            except Exception as error:
                results.put(type(error).__name__)
        finally:
            await repository.close()

    asyncio.run(run())
