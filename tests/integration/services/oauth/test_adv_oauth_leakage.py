"""Original adversarial cases migrated to A4 credential OAuth.

Case names and parameter matrices retain their origin. Scoped metadata/grants
replace singleton statuses and slots; GET is observational and explicit POST
polls make at most one vendor attempt. Monitoring never polls OAuth implicitly.
"""

import logging
import re
from pathlib import Path

from tests.fixtures.api_keys import database_dump
from tests.fixtures.vault_oauth import vault_oauth_case as vault_oauth_case
from tests.integration.services.oauth.oauth_stubs import (
    ACCESS_TOKEN_VALUE,
    CLIENT_SECRET_VALUE,
    REFRESH_TOKEN_VALUE,
    TOKEN_SENTINELS,
    collect_sqlite_texts,
    find_leaked_secrets,
)


async def test_no_token_material_in_logs_and_error_bodies(oauth_case, caplog):
    """Origin test_adv_oauth_leakage.py::test_no_token_material_in_logs_and_error_bodies."""
    case = oauth_case
    bodies = []
    with caplog.at_level(logging.DEBUG):
        for outcome in ("access_denied", "expired_token", "invalid_grant"):
            case.stub.poll_script = [outcome]
            bodies.append(case.client.post(case.path + "/device", headers=case.headers))
            bodies.append(case.client.post(case.path + "/poll", headers=case.headers))
            bodies.append(case.client.delete(case.path, headers=case.headers))
        await case.connect()
        bodies.append(case.client.post(case.path + "/device", headers=case.headers))
        case.stub.refresh_reject = "invalid_grant"
        await case.refresh()
        bodies.append(case.client.get("/dashboard", headers=case.headers))
    for body in bodies:
        assert not find_leaked_secrets(body.text)
    assert not find_leaked_secrets(caplog.text)
    await case.assert_no_leaks(*bodies)


async def test_tokens_in_vault_not_in_db(oauth_case):
    """Origin test_adv_oauth_leakage.py::test_tokens_in_vault_not_in_db."""
    case = oauth_case
    await case.connect()
    assert await case.token() == ACCESS_TOKEN_VALUE
    assert await case.token("refresh") == REFRESH_TOKEN_VALUE
    assert await case.token("client") == CLIENT_SECRET_VALUE
    assert await case.token("device") is None
    await case.assert_no_leaks()
    for text in collect_sqlite_texts(Path(case.repository._engine.url.database)):
        assert not find_leaked_secrets(text)
    assert not find_leaked_secrets(database_dump(case.repository))


async def test_status_is_fingerprint_only(vault_oauth_case):
    """Origin test_adv_oauth_leakage.py::test_status_is_fingerprint_only."""
    case = vault_oauth_case
    await case.connect()
    probe = case.client.get(case.path, headers=case.headers)
    assert probe.status_code == 200
    assert not find_leaked_secrets(probe.text)
    assert "access_token" not in probe.text.lower() and "refresh_token" not in probe.text.lower()
    await case.assert_no_leaks(probe)


async def test_quota_payload_carries_no_tokens(oauth_case):
    """Origin test_adv_oauth_leakage.py::test_quota_payload_carries_no_tokens."""
    case = oauth_case
    await case.connect()
    snapshot = await case.balance()
    body = snapshot.model_dump_json()
    assert not find_leaked_secrets(body)
    response = case.client.get("/dashboard", headers=case.headers)
    assert response.status_code == 200
    assert not find_leaked_secrets(response.text)
    await case.assert_no_leaks(response, body)


SECRET_LIKE_PATTERNS = (r"sk-[A-Za-z0-9]{8,}", r"ghp_[A-Za-z0-9]{8,}")


def test_checked_in_fixtures_hold_no_real_secrets() -> None:
    roots = [Path("tests/integration/services/oauth"), Path("tests/bdd/features")]
    offenders: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in {".py", ".feature", ".md"}:
                continue
            if path.name == "oauth_stubs.py":
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for pattern in SECRET_LIKE_PATTERNS:
                if re.search(pattern, text):
                    offenders.append(str(path) + ":" + pattern)
            for sentinel in TOKEN_SENTINELS:
                if sentinel in text:
                    offenders.append(str(path) + ":sentinel-copy")
    assert offenders == [], "secret-like material in fixtures: " + repr(offenders)
