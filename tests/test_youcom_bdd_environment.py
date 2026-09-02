"""BDD environment hooks: ``@youcom`` scenarios skip before adapter construction.

Reviewer gap: ``before_scenario`` used to construct ``TavilyAdapter`` before
checking the ``@youcom`` tag. With both provider keys absent, TavilyAdapter
fails closed and the You.com scenario aborted instead of skipping. These tests
lock the fixed ordering (skip first, then construct) and the preserved Tavily
lifecycle (construct on non-You.com scenarios, close in ``after_scenario``).
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from freesearch.contracts import ProviderError
from freesearch.resilience import ProviderOperationError

# ``features`` is an uninstalled namespace package at the repo root; make it
# importable regardless of pytest's sys.path manipulation.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from features import environment  # noqa: E402

from freesearch.adapters import youcom as youcom_module  # noqa: E402


class _FakeClient:
    """Stand-in for the factory-created HTTP client."""

    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _FakeScenario:
    """Minimal behave Scenario stand-in recording tags and skip calls."""

    def __init__(self, tags: list[str]) -> None:
        self.tags = tags
        self.skipped = False
        self.skip_reason: str | None = None

    def skip(self, reason: str | None = None) -> None:
        self.skipped = True
        self.skip_reason = reason


class _RecordingAdapter:
    """Records every construction; each instance records its own close."""

    instances: ClassVar[list["_RecordingAdapter"]] = []

    def __init__(self, client: object) -> None:
        self.client = client
        self.closed = False
        type(self).instances.append(self)

    async def aclose(self) -> None:
        self.closed = True


class _ForbiddenAdapter:
    """Construction raises: proves the adapter was never built."""

    def __init__(self, client: object) -> None:
        raise AssertionError("adapter must not be constructed")


class _FailClosedAdapter:
    """Mirrors TavilyAdapter's fail-closed construction without a key."""

    def __init__(self, client: object) -> None:
        raise ProviderOperationError(
            ProviderError(
                provider="tavily",
                code="configuration_error",
                message="no Tavily API key configured",
            )
        )


class _StubResolver:
    """Resolver holding a key only for the named providers (by ``value``)."""

    def __init__(self, *providers: str) -> None:
        self._present = set(providers)

    def get(self, provider: Any) -> object | None:
        return object() if provider.value in self._present else None


def _run_scenario(monkeypatch: pytest.MonkeyPatch, tags: list[str], *keys: str) -> None:
    """Patch the hooks' dependencies, then drive before_all/before_scenario."""
    fake_client = _FakeClient()
    monkeypatch.setattr(environment, "get_provider_secret_resolver", lambda: _StubResolver(*keys))
    monkeypatch.setattr(environment, "create_async_client", lambda: fake_client)

    context = SimpleNamespace()
    environment.before_all(context)
    context.scenario = _FakeScenario(tags)
    environment.before_scenario(context, context.scenario)
    return context


def _close_after(context: SimpleNamespace) -> None:
    environment.after_scenario(context, context.scenario)


def test_youcom_scenario_skips_before_tavily_adapter_when_both_keys_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No keys at all: the ``@youcom`` scenario must skip cleanly - TavilyAdapter
    is never constructed, so its fail-closed error cannot abort the scenario."""
    monkeypatch.setattr(environment, "TavilyAdapter", _ForbiddenAdapter)
    context = _run_scenario(monkeypatch, ["youcom", "live"])
    scenario = context.scenario
    try:
        assert scenario.skipped is True
        assert scenario.skip_reason is not None
        assert "FREESEARCH_YOU_API_KEY" in scenario.skip_reason
        assert context.adapter is None
        assert context.youcom_adapter is None
    finally:
        _close_after(context)

    assert context.http_client.closed is True


def test_youcom_scenario_without_youcom_key_skips_even_when_tavily_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A You.com scenario needs the You.com key; a Tavily-only environment still
    skips instead of building the Tavily adapter."""
    monkeypatch.setattr(environment, "TavilyAdapter", _ForbiddenAdapter)
    context = _run_scenario(monkeypatch, ["youcom", "live"], "tavily")
    scenario = context.scenario
    try:
        assert scenario.skipped is True
        assert context.adapter is None
        assert context.youcom_adapter is None
    finally:
        _close_after(context)


def test_youcom_scenario_with_key_builds_youcom_adapter_and_never_tavily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With a You.com key the adapter is built for the scenario; the Tavily
    adapter is not constructed for You.com scenarios."""
    _RecordingAdapter.instances.clear()
    monkeypatch.setattr(environment, "TavilyAdapter", _ForbiddenAdapter)
    monkeypatch.setattr(youcom_module, "YoucomAdapter", _RecordingAdapter)

    context = _run_scenario(monkeypatch, ["youcom", "live"], "you")
    scenario = context.scenario
    try:
        assert scenario.skipped is False
        assert context.youcom_adapter is not None
        assert context.youcom_adapter.client is context.http_client
        assert _RecordingAdapter.instances == [context.youcom_adapter]
        assert context.adapter is None
    finally:
        _close_after(context)

    assert context.youcom_adapter.closed is True
    assert context.http_client.closed is True


def test_tavily_scenario_still_constructs_and_cleans_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-You.com scenarios keep the working Tavily lifecycle: adapter built on
    the factory client, closed in ``after_scenario`` along with the client."""
    _RecordingAdapter.instances.clear()
    monkeypatch.setattr(environment, "TavilyAdapter", _RecordingAdapter)

    context = _run_scenario(monkeypatch, ["live", "search"], "tavily")
    scenario = context.scenario
    try:
        assert scenario.skipped is False
        assert context.adapter is not None
        assert context.adapter.client is context.http_client
        assert context.youcom_adapter is None
        assert _RecordingAdapter.instances == [context.adapter]
    finally:
        _close_after(context)

    assert context.adapter.closed is True
    assert context.http_client.closed is True


def test_non_youcom_scenario_without_keys_still_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Tavily fail-closed contract is preserved for non-You.com scenarios:
    no key means construction raises instead of a silent skip."""
    monkeypatch.setattr(environment, "get_provider_secret_resolver", lambda: _StubResolver())
    monkeypatch.setattr(environment, "create_async_client", lambda: _FakeClient())
    monkeypatch.setattr(environment, "TavilyAdapter", _FailClosedAdapter)

    context = SimpleNamespace()
    environment.before_all(context)
    scenario = _FakeScenario(["live", "search"])
    with pytest.raises(ProviderOperationError) as excinfo:
        environment.before_scenario(context, scenario)

    assert excinfo.value.error.code == "configuration_error"
    assert scenario.skipped is False
    assert context.adapter is None
    # The scenario failed before cleanup ran; close the loop manually.
    context.loop.close()
