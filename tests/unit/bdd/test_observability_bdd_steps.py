"""Mock-only checks of scenario-owned observability client lifespans."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.bdd.features import environment  # noqa: E402
from tests.bdd.features.steps import observability_steps as steps  # noqa: E402


def test_requests_share_one_entered_client_without_owning_its_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = object()
    context = SimpleNamespace(otel_app=app)
    client = MagicMock()
    client.__enter__.return_value = client
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(steps, "TestClient", factory)

    for _ in range(3):
        with steps._client_for(context) as borrowed:
            assert borrowed is client

    factory.assert_called_once_with(app, raise_server_exceptions=False)
    client.__enter__.assert_called_once_with()
    client.__exit__.assert_not_called()
    assert context.otel_client is client


def test_different_scenarios_own_different_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    clients = [MagicMock(), MagicMock()]
    for client in clients:
        client.__enter__.return_value = client
    factory = MagicMock(side_effect=clients)
    monkeypatch.setattr(steps, "TestClient", factory)
    contexts = [SimpleNamespace(), SimpleNamespace()]

    for context, client in zip(contexts, clients, strict=True):
        steps._reset_otel_state(context)
        assert context.otel_client is None
        context.otel_app = object()
        with steps._client_for(context) as borrowed:
            assert borrowed is client
        assert context.otel_client is client

    assert factory.call_count == 2


def test_replacement_closes_old_client_before_building_and_starting_new_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    original_app, replacement_app = object(), object()
    context = SimpleNamespace(otel_app=original_app, repository=object())
    old_client, new_client = MagicMock(), MagicMock()
    old_client.__enter__.return_value = old_client
    old_client.__exit__.side_effect = lambda *_: events.append("old exit")
    new_client.__enter__.side_effect = lambda: events.append("new enter") or new_client
    monkeypatch.setattr(steps, "TestClient", MagicMock(side_effect=[old_client, new_client]))

    def build_app(adapters: object, *, repository: object) -> object:
        assert context.otel_client is None
        assert context.otel_app is original_app
        assert repository is context.repository
        events.append("build app")
        return replacement_app

    def post_fetch(actual_context: SimpleNamespace, url: str) -> None:
        assert actual_context is context
        assert url == "https://example.com/boom"
        assert context.otel_app is replacement_app
        with steps._client_for(context) as borrowed:
            assert borrowed is new_client

    monkeypatch.setattr(steps, "create_app", build_app)
    monkeypatch.setattr(steps, "_post_fetch", post_fetch)
    with steps._client_for(context):
        pass
    events.clear()

    steps.step_when_traced_fetch_failing(context, "https://example.com/boom")

    assert events == ["old exit", "build app", "new enter"]
    old_client.__exit__.assert_called_once_with(None, None, None)
    new_client.__exit__.assert_not_called()
    assert context.otel_client is new_client

    context.loop = asyncio.new_event_loop()
    try:
        environment.after_scenario(context, None)
    finally:
        if not context.loop.is_closed():
            context.loop.close()
    old_client.__exit__.assert_called_once_with(None, None, None)
    new_client.__exit__.assert_called_once_with(None, None, None)


def test_scenario_cleanup_exits_final_client_once_before_closing_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.side_effect = lambda *_: events.append("client exit")
    monkeypatch.setattr(steps, "TestClient", MagicMock(return_value=client))

    async def close_repository() -> None:
        events.append("repository close")

    loop = asyncio.new_event_loop()
    repository = SimpleNamespace(close=AsyncMock(side_effect=close_repository))
    context = SimpleNamespace(otel_app=object(), repository=repository, loop=loop)
    try:
        with steps._client_for(context):
            pass
        with steps._client_for(context):
            pass
        assert events == []
        environment.after_scenario(context, None)
    finally:
        if not loop.is_closed():
            loop.close()

    assert events == ["client exit", "repository close"]
    client.__exit__.assert_called_once_with(None, None, None)
    repository.close.assert_awaited_once_with()
