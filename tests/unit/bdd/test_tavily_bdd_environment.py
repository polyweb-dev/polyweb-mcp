"""Unit tests for the Tavily BDD environment hooks. No live I/O."""

import asyncio
from types import SimpleNamespace

import tests.bdd.features.environment as environment


def _offline_scenario() -> SimpleNamespace:
    return SimpleNamespace(tags=["limits"], effective_tags=["limits"])


def test_offline_limits_scenario_builds_loop_client_without_adapter() -> None:
    context = SimpleNamespace()
    environment.before_scenario(context, _offline_scenario())
    try:
        assert context.loop is not None
        assert context.http_client is not None
        assert context.adapter is None
        assert context.search_response is None
        assert context.fetch_response is None
        assert context.quota_snapshot is None
        assert context.last_error is None
    finally:
        environment.after_scenario(context, _offline_scenario())


def test_offline_hook_resets_state_between_scenarios() -> None:
    context = SimpleNamespace()
    environment.before_scenario(context, _offline_scenario())
    try:
        context.search_response = object()
        context.last_error = ValueError("stale")
    finally:
        environment.after_scenario(context, _offline_scenario())
    fresh = SimpleNamespace()
    environment.before_scenario(fresh, _offline_scenario())
    try:
        assert fresh.search_response is None
        assert fresh.last_error is None
    finally:
        environment.after_scenario(fresh, _offline_scenario())


def test_after_scenario_closes_loop_and_client() -> None:
    context = SimpleNamespace()
    environment.before_scenario(context, _offline_scenario())
    loop = context.loop
    assert isinstance(loop, asyncio.AbstractEventLoop)
    environment.after_scenario(context, _offline_scenario())
    assert loop.is_closed()
