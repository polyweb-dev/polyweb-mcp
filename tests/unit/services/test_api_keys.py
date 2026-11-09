"""Unit tests for project API key policy without database I/O (A1, TASK-000041).

Key format, parsing, digest, status, scope filtering, rotation lifetime and
overlap arithmetic, and the use-recorder throttle are deterministic and run
with fixed clocks and fakes. Storage-backed behavior lives in
``tests/integration/services/test_api_keys.py``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import SecretStr

from freesearch.models.projects import (
    API_KEY_SCOPES,
    DEFAULT_API_KEY_LIFETIME_DAYS,
    PROJECT_API_KEY_PREFIX,
    ApiKeyStatus,
    ProjectApiKeyRotate,
)
from freesearch.persistence.api_keys import StoredApiKey
from freesearch.services.api_keys import (
    API_KEY_PREFIX_LENGTH,
    API_KEY_SECRET_BYTES,
    ApiKeyService,
    ApiKeyUseRecorder,
    ApiKeyVerifier,
    api_key_status,
    execution_scopes,
    generate_api_key,
    parse_api_key,
    principal_for,
    verifier_digest,
)

_NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
_KEY_SHAPE = re.compile(r"^fs_live_[a-z2-7]{12}_[A-Za-z0-9_-]{43}$")


def _stored(**overrides: Any) -> StoredApiKey:
    base: dict[str, Any] = {
        "id": uuid4(),
        "project_id": uuid4(),
        "label": "unit",
        "prefix": "abcdefghijkl",
        "verifier_digest": "0" * 64,
        "scopes": frozenset(API_KEY_SCOPES),
        "created_by": uuid4(),
        "created_at": _NOW - timedelta(days=10),
        "expires_at": _NOW + timedelta(days=80),
        "revoked_at": None,
        "last_used_at": None,
        "rotated_from_id": None,
        "version": 1,
    }
    base.update(overrides)
    return StoredApiKey(**base)


def test_generated_key_format_entropy_and_digest() -> None:
    keys = [generate_api_key() for _ in range(200)]
    raws = [item.key.get_secret_value() for item in keys]

    for item, raw in zip(keys, raws, strict=True):
        assert _KEY_SHAPE.match(raw), "unexpected key shape"
        assert raw.startswith(PROJECT_API_KEY_PREFIX + item.prefix + "_")
        assert len(item.prefix) == API_KEY_PREFIX_LENGTH
        secret = raw[len(PROJECT_API_KEY_PREFIX) + API_KEY_PREFIX_LENGTH + 1 :]
        assert item.verifier_digest == hashlib.sha256(secret.encode("ascii")).hexdigest()
        assert item.verifier_digest != hashlib.sha256(raw.encode("ascii")).hexdigest()
    # 256-bit secrets and 60-bit prefixes: no collision in a small sample.
    assert len(set(raws)) == len(raws)
    assert len({item.prefix for item in keys}) == len(keys)
    assert API_KEY_SECRET_BYTES * 8 >= 256


def test_generated_key_material_never_reveals_itself() -> None:
    material = generate_api_key()
    raw = material.key.get_secret_value()
    secret = raw[len(PROJECT_API_KEY_PREFIX) + API_KEY_PREFIX_LENGTH + 1 :]

    for text in (repr(material), str(material)):
        assert raw not in text
        assert secret not in text
        assert material.verifier_digest not in text
    parsed = parse_api_key(material.key)
    assert parsed is not None
    assert parsed.prefix == material.prefix
    assert secret not in repr(parsed)
    assert verifier_digest(parsed.secret) == material.verifier_digest


@pytest.mark.parametrize(
    "candidate",
    [
        "",
        "fs_live_",
        "fs_test_abcdefghijkl_" + "a" * 43,
        "FS_LIVE_abcdefghijkl_" + "a" * 43,
        "fs_live_abcdefghijk_" + "a" * 44,
        "fs_live_abcdefghijkl-" + "a" * 43,
        "fs_live_ABCDEFGHIJKL_" + "a" * 43,
        "fs_live_abcdefghijk1_" + "a" * 43,
        "fs_live_abcdefghijkl_" + "a" * 42,
        "fs_live_abcdefghijkl_" + "a" * 44,
        "fs_live_abcdefghijkl_" + "a" * 42 + "=",
        "fs_live_abcdefghijkl_" + "a" * 42 + " ",
        " fs_live_abcdefghijkl_" + "a" * 42,
        "fs_live_abcdefghijkl_" + "a" * 42 + "\u00e9",
        "Bearer fs_live_abcdefghijkl_" + "a" * 43,
    ],
)
def test_malformed_keys_are_rejected_by_format_alone(candidate: str) -> None:
    assert parse_api_key(SecretStr(candidate)) is None


async def test_verifier_rejects_malformed_and_absent_keys_without_storage() -> None:
    repository = AsyncMock()
    verifier = ApiKeyVerifier(repository, clock=lambda: _NOW)

    assert await verifier.verify(None) is None
    assert await verifier.verify("") is None
    assert await verifier.verify("fs_live_short") is None
    assert await verifier.verify(SecretStr("not-a-key")) is None
    repository.session.assert_not_called()


def test_status_uses_the_authoritative_clock_with_inclusive_expiry() -> None:
    assert api_key_status(_stored(), _NOW) is ApiKeyStatus.ACTIVE
    assert api_key_status(_stored(expires_at=None), _NOW) is ApiKeyStatus.ACTIVE
    assert api_key_status(_stored(expires_at=_NOW), _NOW) is ApiKeyStatus.EXPIRED
    assert (
        api_key_status(_stored(expires_at=_NOW - timedelta(microseconds=1)), _NOW)
        is ApiKeyStatus.EXPIRED
    )
    # Revocation wins over a live or past expiry.
    assert api_key_status(_stored(revoked_at=_NOW), _NOW) is ApiKeyStatus.REVOKED
    assert (
        api_key_status(_stored(revoked_at=_NOW, expires_at=_NOW - timedelta(days=1)), _NOW)
        is ApiKeyStatus.REVOKED
    )


def test_principal_holds_only_stored_execution_scopes() -> None:
    stored = _stored(scopes=frozenset({"search.execute", "tokens.manage", "members.manage"}))
    assert execution_scopes(stored.scopes) == frozenset({"search.execute"})
    principal = principal_for(stored)
    assert principal.scopes == frozenset({"search.execute"})
    assert principal.project_id == stored.project_id
    assert principal.api_key_id == stored.id
    assert principal.actor_id == stored.id
    assert principal.actor_type.value == "project_api_key"


@pytest.mark.parametrize(
    ("old_expiry", "body", "expected"),
    [
        # Omitted: keep the old lifetime, measured from the old issue time.
        (timedelta(days=80), {}, timedelta(days=90)),
        (timedelta(days=-5), {}, timedelta(days=5)),
        # Omitted and no old expiry: the replacement never expires either.
        (None, {}, None),
        # Explicit null: no expiration, even when the old key had one.
        (timedelta(days=80), {"expires_at": None}, None),
    ],
)
def test_rotation_keeps_the_lifetime_unless_changed(
    old_expiry: timedelta | None, body: dict[str, Any], expected: timedelta | None
) -> None:
    old = _stored(expires_at=None if old_expiry is None else _NOW + old_expiry)
    resolved = ApiKeyService._rotated_expiry(old, ProjectApiKeyRotate.model_validate(body), _NOW)
    if expected is None:
        assert resolved is None
    else:
        assert resolved == _NOW + expected


def test_rotation_explicit_expiry_is_used_verbatim() -> None:
    target = datetime.now(UTC).replace(microsecond=0) + timedelta(days=3)
    old = _stored(expires_at=None)
    resolved = ApiKeyService._rotated_expiry(old, ProjectApiKeyRotate(expires_at=target), _NOW)
    assert resolved == target


@pytest.mark.parametrize(
    ("old_expiry", "overlap", "expected_expiry", "revoked"),
    [
        (timedelta(days=80), 86_400, timedelta(seconds=86_400), False),
        (None, 86_400, timedelta(seconds=86_400), False),
        # The overlap never extends an earlier own expiry.
        (timedelta(hours=1), 86_400, timedelta(hours=1), False),
        (timedelta(days=80), 0, timedelta(days=80), True),
    ],
)
async def test_rotation_overlap_bounds_or_revokes_the_old_key(
    old_expiry: timedelta | None,
    overlap: int,
    expected_expiry: timedelta,
    revoked: bool,
) -> None:
    old = _stored(expires_at=None if old_expiry is None else _NOW + old_expiry)
    keys = AsyncMock()
    keys.set_expiry.return_value = True
    keys.revoke.return_value = True

    previous = await ApiKeyService._end_overlap(keys, old, overlap, _NOW)

    assert previous == _NOW + expected_expiry
    if revoked:
        keys.revoke.assert_awaited_once_with(
            project_id=old.project_id, api_key_id=old.id, revoked_at=_NOW
        )
        keys.set_expiry.assert_not_called()
    else:
        keys.revoke.assert_not_called()
        if old.expires_at == _NOW + expected_expiry:
            keys.set_expiry.assert_not_called()
        else:
            keys.set_expiry.assert_awaited_once_with(
                project_id=old.project_id, api_key_id=old.id, expires_at=_NOW + expected_expiry
            )


def test_default_lifetime_constant_is_90_days() -> None:
    assert DEFAULT_API_KEY_LIFETIME_DAYS == 90


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def test_use_recorder_throttles_per_key_and_never_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock()
    recorder = ApiKeyUseRecorder(interval_seconds=60, monotonic=clock)
    written: list[tuple[object, object]] = []

    async def _record(repository: object, project_id: object, api_key_id: object, used_at: object):
        written.append((api_key_id, used_at))

    monkeypatch.setattr(ApiKeyUseRecorder, "_record", staticmethod(_record))
    first = _stored()
    second = _stored()

    recorder.schedule(object(), first, _NOW)  # type: ignore[arg-type]
    recorder.schedule(object(), first, _NOW + timedelta(seconds=1))  # type: ignore[arg-type]
    recorder.schedule(object(), second, _NOW)  # type: ignore[arg-type]
    await recorder.drain()
    assert [item[0] for item in written] == [first.id, second.id]

    # A stored stamp inside the interval also suppresses a write.
    clock.now += 61
    recent = replace(first, last_used_at=_NOW + timedelta(seconds=30))
    recorder.schedule(object(), recent, _NOW + timedelta(seconds=40))  # type: ignore[arg-type]
    await recorder.drain()
    assert len(written) == 2

    recorder.schedule(object(), first, _NOW + timedelta(seconds=120))  # type: ignore[arg-type]
    await recorder.drain()
    assert len(written) == 3


async def test_use_recorder_swallows_storage_failures(caplog: pytest.LogCaptureFixture) -> None:
    from unittest.mock import MagicMock

    recorder = ApiKeyUseRecorder(interval_seconds=0)
    repository = MagicMock()
    repository.session.side_effect = RuntimeError("database is locked fs_live_secret")

    recorder.schedule(repository, _stored(), _NOW)
    await recorder.drain()

    assert "fs_live_secret" not in caplog.text


# --- R3: denial events are throttled, queued off-path and bounded ---------------


async def test_denials_are_throttled_per_key_and_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    import freesearch.services.api_keys as api_keys_module

    written: list[tuple[object, str]] = []

    async def _record(repository: object, stored: StoredApiKey, *, action: str, reason: str, **_):
        written.append((stored.id, reason))

    monkeypatch.setattr(api_keys_module, "record_api_key_denial", _record)
    clock = _Clock()
    recorder = ApiKeyUseRecorder(interval_seconds=60, monotonic=clock)
    key, other = _stored(), _stored()

    for _ in range(25):
        recorder.schedule_denial(object(), key, action="a", reason="invalid_secret")  # type: ignore[arg-type]
    recorder.schedule_denial(object(), key, action="a", reason="revoked")  # type: ignore[arg-type]
    recorder.schedule_denial(object(), other, action="a", reason="invalid_secret")  # type: ignore[arg-type]
    await recorder.drain()
    assert written == [
        (key.id, "invalid_secret"),
        (key.id, "revoked"),
        (other.id, "invalid_secret"),
    ]

    clock.now += 59
    recorder.schedule_denial(object(), key, action="a", reason="invalid_secret")  # type: ignore[arg-type]
    await recorder.drain()
    assert len(written) == 3
    clock.now += 2
    recorder.schedule_denial(object(), key, action="a", reason="invalid_secret")  # type: ignore[arg-type]
    await recorder.drain()
    assert written[-1] == (key.id, "invalid_secret")
    assert len(written) == 4


async def test_full_queue_drops_without_raising_and_logs_prefix_only(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import freesearch.services.api_keys as api_keys_module

    written: list[str] = []

    async def _record(repository: object, stored: StoredApiKey, *, action: str, reason: str, **_):
        written.append(stored.prefix)

    monkeypatch.setattr(api_keys_module, "record_api_key_denial", _record)
    caplog.set_level("WARNING")
    recorder = ApiKeyUseRecorder(interval_seconds=60, max_pending=2)
    secret = "S" * 43
    keys = [_stored(prefix=f"pref{index:08d}", verifier_digest="d" * 64) for index in range(5)]

    # Scheduled synchronously: the worker cannot run in between, so the queue fills.
    for stored in keys:
        recorder.schedule_denial(object(), stored, action="a", reason="revoked")  # type: ignore[arg-type]
    await recorder.drain()

    assert written == [keys[0].prefix, keys[1].prefix]
    dropped = [
        record.getMessage() for record in caplog.records if "queue is full" in record.getMessage()
    ]
    assert len(dropped) == 3
    for message in dropped:
        assert secret not in message
        assert "d" * 64 not in message
    assert keys[4].prefix in dropped[-1]
    # A dropped job did not consume the throttle: it can be written later.
    recorder.schedule_denial(object(), keys[4], action="a", reason="revoked")  # type: ignore[arg-type]
    await recorder.drain()
    assert written[-1] == keys[4].prefix


async def test_scheduling_never_waits_on_a_stalled_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    import time as time_module

    import freesearch.services.api_keys as api_keys_module

    release = asyncio.Event()

    async def _stalled(repository: object, stored: StoredApiKey, **_: object) -> None:
        await release.wait()

    monkeypatch.setattr(api_keys_module, "record_api_key_denial", _stalled)
    recorder = ApiKeyUseRecorder(interval_seconds=60)
    started = time_module.perf_counter()
    for _ in range(3):
        recorder.schedule_denial(object(), _stored(), action="a", reason="revoked")  # type: ignore[arg-type]
    await asyncio.sleep(0)
    assert time_module.perf_counter() - started < 0.5
    release.set()
    await recorder.drain()
