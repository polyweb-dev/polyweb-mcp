"""Live vault-backed You.com search+fetch (manual-only, @live).

Skips gracefully without a harness key; never hardcodes a real key. The real
You.com key comes only from the harness env (FREESEARCH_YOU_API_KEY) and is
stored through the vault (PUT /secret) under passphrase encryption
(FREESEARCH_ENCRYPTION_KEY when present, else an auto-generated tmp key
file). Search+fetch run against the live vendor; logs/responses/rows are
swept for key material.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from behave import given, then, when  # type: ignore[import-untyped]
from fastapi.testclient import TestClient

from freesearch.configuration.config import get_settings
from freesearch.infrastructure.secrets import ProviderName
from freesearch.models.contracts import FetchRequest, SearchRequest
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
from freesearch.routers.control import _build_with_resolved_secret, _resolve_secret
from tests.encrypted_secrets_helpers import assert_no_sentinels
from tests.fixtures.auth import (
    TEMP_PASSWORD,
    configure_bdd_secret,
    promote_to_system_admin,
    temp_email,
)
from tests.integration.services.oauth.oauth_stubs import collect_sqlite_texts

YOU_ENV = "FREESEARCH_YOU_API_KEY"
PASSPHRASE_ENV = "FREESEARCH_ENCRYPTION_KEY"
KEY_FILE_ENV = "FREESEARCH_ENCRYPTION_KEY_FILE"


class _RecordHandler(logging.Handler):
    def __init__(self, sink: list[str]) -> None:
        super().__init__(level=logging.DEBUG)
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        self._sink.append(self.format(record))


def _push_cleanup(context: Any, cleanup: Any) -> None:
    cleanups = getattr(context, "enc_cleanups", None)
    if cleanups is None:
        context.enc_cleanups = cleanups = []
    cleanups.append(cleanup)


@given("a live vault-backed You.com control API")
def step_given_live_vault_youcom(context: Any) -> None:
    live_key = os.environ.get(YOU_ENV)
    if not live_key:
        context.scenario.skip(
            f"{YOU_ENV} is not set (harness live-gate reads the process env only). "
            "Live vault You.com scenario skipped without a harness key."
        )
        return
    context.live_you_key = live_key
    passphrase = os.environ.get(PASSPHRASE_ENV)

    saved_cwd = Path.cwd()
    _push_cleanup(context, lambda: os.chdir(saved_cwd))
    scenario_dir = saved_cwd / f"freesearch-live-you-{uuid4().hex}"
    scenario_dir.mkdir()
    context.scenario_dir = str(scenario_dir)
    _push_cleanup(context, lambda: shutil.rmtree(scenario_dir, ignore_errors=True))
    os.chdir(scenario_dir)

    saved_environ = dict(os.environ)

    def _restore() -> None:
        os.environ.clear()
        os.environ.update(saved_environ)
        get_settings.cache_clear()

    _push_cleanup(context, _restore)
    # Vault-only: drop provider env keys so only the PUT vault value resolves.
    # The live key itself was already captured above and is never re-exported.
    for var in (
        "FREESEARCH_EXA_API_KEY",
        "FREESEARCH_FIRECRAWL_API_KEY",
        "FREESEARCH_TAVILY_API_KEY",
        "FREESEARCH_PARALLEL_API_KEY",
        YOU_ENV,
        "FREESEARCH_BRAVE_SEARCH_API_KEY",
        "FREESEARCH_KEENABLE_API_KEY",
    ):
        os.environ.pop(var, None)
    if passphrase:
        os.environ[PASSPHRASE_ENV] = passphrase
    else:
        os.environ.pop(PASSPHRASE_ENV, None)
    os.environ[KEY_FILE_ENV] = str(scenario_dir / ".secret_key")
    get_settings.cache_clear()
    configure_bdd_secret(context)

    db_path = scenario_dir / f"live-you-{uuid4().hex}.db"
    context.database_path = str(db_path)
    context.repository = context.loop.run_until_complete(SQLiteRepository.open(db_path))
    context.app = create_app([], repository=context.repository)

    context.captured_logs = []
    handler = _RecordHandler(context.captured_logs)
    root = logging.getLogger()
    root.addHandler(handler)
    _push_cleanup(context, lambda: root.removeHandler(handler))

    # Vault writes need the Admin role.
    email = temp_email("live-you-admin")
    with TestClient(context.app) as client:
        registered = client.post("/auth/register", json={"email": email, "password": TEMP_PASSWORD})
        assert registered.status_code == 201, registered.text
        context.loop.run_until_complete(promote_to_system_admin(context.repository, email))
        logged_in = client.post(
            "/auth/jwt/login", data={"username": email, "password": TEMP_PASSWORD}
        )
        assert logged_in.status_code == 200, logged_in.text
        context.live_auth_headers = {"Authorization": f"Bearer {logged_in.json()['access_token']}"}
        put = client.put(
            "/api/v1/providers/you/secret",
            json={"key": live_key},
            headers=context.live_auth_headers,
        )
        assert put.status_code == 200, put.text
        assert put.json()["source"] == "encrypted_db"
        context.live_put_body = put.text

    async def _build_live_adapter() -> Any:
        from freesearch.adapters.registry import adapter_factory

        key, source = await _resolve_secret(ProviderName.YOU, context.app.state.secret_store)
        assert key is not None and source == "encrypted_db", (
            "RED: vault PUT must resolve via encrypted_db before live search"
        )
        factory = adapter_factory("you")
        assert factory is not None
        return _build_with_resolved_secret(factory, context.http_client, key)

    context.youcom_live_adapter = context.loop.run_until_complete(_build_live_adapter())


@when('I run a live vault search for "{query}" with limit {limit:d}')
def step_when_live_vault_search(context: Any, query: str, limit: int) -> None:
    request = SearchRequest(
        project_id="00000000-0000-4000-8000-0000000000aa", query=query, limit=limit
    )
    context.live_query = query
    context.live_search = context.loop.run_until_complete(
        context.youcom_live_adapter.search(request)
    )


@when("I fetch the first live vault result URL")
def step_when_live_vault_fetch(context: Any) -> None:
    results = context.live_search.results
    assert results, "live search returned no results to fetch"
    first_url = results[0].url
    context.live_fetch_url = str(first_url)
    request = FetchRequest(
        project_id="00000000-0000-4000-8000-0000000000aa", url=first_url, max_chars=2000
    )
    context.live_fetch = context.loop.run_until_complete(context.youcom_live_adapter.fetch(request))


@then("the live vault search and fetch should succeed")
def step_then_live_vault_succeed(context: Any) -> None:
    search = context.live_search
    assert search.provider == "you"
    assert search.query == context.live_query
    assert len(search.results) > 0
    for result in search.results:
        assert result.title and result.url and result.snippet
    fetch = context.live_fetch
    assert fetch.provider == "you"
    assert fetch.document is not None
    assert str(fetch.document.url).rstrip("/") == context.live_fetch_url.rstrip("/")
    assert isinstance(fetch.document.content, str) and fetch.document.content.strip()


@then("live vault logs and responses should contain no key material")
def step_then_live_vault_redacted(context: Any) -> None:
    key: str = context.live_you_key
    assert key and len(key) >= 4
    haystack_logs = "\n".join(context.captured_logs)
    assert_no_sentinels(haystack_logs, (key,), "live captured logs")
    bodies = (
        context.live_put_body
        + context.live_search.model_dump_json()
        + context.live_fetch.model_dump_json()
    )
    assert_no_sentinels(bodies, (key,), "live response bodies")
    db_text = "\n".join(collect_sqlite_texts(Path(context.database_path)))
    assert_no_sentinels(db_text, (key,), "live database file")
