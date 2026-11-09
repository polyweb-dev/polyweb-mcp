"""BDD environment hooks: ``@youcom`` scenarios skip before adapter construction.

Reviewer gap: ``before_scenario`` used to construct ``TavilyAdapter`` before
checking the ``@youcom`` tag. With both provider keys absent, TavilyAdapter
fails closed and the You.com scenario aborted instead of skipping. These tests
lock the fixed ordering (skip first, then construct) and the preserved Tavily
lifecycle (construct on non-You.com scenarios, close in ``after_scenario``).

Provider keys now reach the adapters only through the explicit constructor seam
(``api_key=SecretStr(...)``) fed by ``_harness_env_key``; the retired
``get_provider_secret_resolver`` module attribute is never patched or consulted.
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import httpx
import pytest
from pydantic import SecretStr

from polyweb.adapters.tavily import TavilyAdapter
from polyweb.infrastructure.resilience import ProviderOperationError
from polyweb.infrastructure.secrets import PROVIDER_ENV_VARS, ProviderName
from polyweb.models.contracts import ProviderError

# ``features`` is an uninstalled namespace package at the repo root; make it
# importable regardless of pytest's sys.path manipulation.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from polyweb.adapters import youcom as youcom_module  # noqa: E402
from tests.bdd.features import environment  # noqa: E402


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
    """Records every construction and the explicit key it was handed."""

    instances: ClassVar[list["_RecordingAdapter"]] = []

    def __init__(
        self, client: object, *, api_key: SecretStr | None = None, runner: object = None
    ) -> None:
        self.client = client
        self.api_key = api_key
        self.closed = False
        type(self).instances.append(self)

    async def aclose(self) -> None:
        self.closed = True


class _ForbiddenAdapter:
    """Construction raises: proves the adapter was never built."""

    def __init__(
        self, client: object, *, api_key: SecretStr | None = None, runner: object = None
    ) -> None:
        raise AssertionError("adapter must not be constructed")


class _FailClosedAdapter:
    """Mirrors TavilyAdapter's fail-closed construction without a key."""

    def __init__(
        self, client: object, *, api_key: SecretStr | None = None, runner: object = None
    ) -> None:
        raise ProviderOperationError(
            ProviderError(
                provider="tavily",
                code="configuration_error",
                message="no Tavily API key configured",
            )
        )


def _set_harness_keys(monkeypatch: pytest.MonkeyPatch, *providers: ProviderName) -> None:
    """Point the harness key lookup at exactly ``providers`` (process env only).

    ``_harness_env_key`` is the consumer lookup site the hooks read, so the
    process env is the only knob: the retired ``get_provider_secret_resolver``
    seam no longer exists to patch. The values are deliberately fake - no live
    call is ever made.
    """
    for provider, env_var in PROVIDER_ENV_VARS.items():
        if provider in providers:
            monkeypatch.setenv(env_var, f"harness-{provider.value}-key")
        else:
            monkeypatch.delenv(env_var, raising=False)


def _run_scenario(
    monkeypatch: pytest.MonkeyPatch, tags: list[str], *providers: ProviderName
) -> SimpleNamespace:
    """Patch the hooks' dependencies, then drive before_all/before_scenario."""
    fake_client = _FakeClient()
    _set_harness_keys(monkeypatch, *providers)
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
    is never constructed, so its fail-closed error cannot abort the scenario.
    The skip runs before any resource setup, so no loop/client is created."""
    monkeypatch.setattr(environment, "TavilyAdapter", _ForbiddenAdapter)
    context = _run_scenario(monkeypatch, ["youcom", "live"])
    scenario = context.scenario
    try:
        assert scenario.skipped is True
        assert scenario.skip_reason is not None
        assert "POLYWEB_YOU_API_KEY" in scenario.skip_reason
        assert getattr(context, "adapter", None) is None
        assert getattr(context, "youcom_adapter", None) is None
    finally:
        _close_after(context)

    assert not hasattr(context, "loop"), "skip must precede event-loop setup"
    assert not hasattr(context, "http_client"), "skip must precede client setup"


def test_youcom_scenario_without_youcom_key_skips_even_when_tavily_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A You.com scenario needs the You.com key; a Tavily-only environment still
    skips instead of building the Tavily adapter."""
    monkeypatch.setattr(environment, "TavilyAdapter", _ForbiddenAdapter)
    context = _run_scenario(monkeypatch, ["youcom", "live"], ProviderName.TAVILY)
    scenario = context.scenario
    try:
        assert scenario.skipped is True
        assert getattr(context, "adapter", None) is None
        assert getattr(context, "youcom_adapter", None) is None
    finally:
        _close_after(context)


def test_youcom_scenario_with_key_builds_youcom_adapter_and_never_tavily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With a You.com key the adapter is built for the scenario with that key on
    the explicit ``api_key`` seam; the Tavily adapter is never constructed."""
    _RecordingAdapter.instances.clear()
    monkeypatch.setattr(environment, "TavilyAdapter", _ForbiddenAdapter)
    monkeypatch.setattr(youcom_module, "YoucomAdapter", _RecordingAdapter)

    context = _run_scenario(monkeypatch, ["youcom", "live"], ProviderName.YOU)
    scenario = context.scenario
    try:
        assert scenario.skipped is False
        assert context.youcom_adapter is not None
        assert context.youcom_adapter.client is context.http_client
        assert _RecordingAdapter.instances == [context.youcom_adapter]
        assert context.adapter is None
        assert context.youcom_adapter.api_key is not None, (
            "the harness must inject the You.com key via the explicit api_key seam"
        )
        assert context.youcom_adapter.api_key.get_secret_value() == "harness-you-key"
    finally:
        _close_after(context)

    assert context.youcom_adapter.closed is True
    assert context.http_client.closed is True


def test_tavily_scenario_still_constructs_and_cleans_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-You.com scenarios keep the working Tavily lifecycle: adapter built on
    the factory client with the harness key, closed in ``after_scenario`` along
    with the client."""
    _RecordingAdapter.instances.clear()
    monkeypatch.setattr(environment, "TavilyAdapter", _RecordingAdapter)

    context = _run_scenario(monkeypatch, ["live", "search"], ProviderName.TAVILY)
    scenario = context.scenario
    try:
        assert scenario.skipped is False
        assert context.adapter is not None
        assert context.adapter.client is context.http_client
        assert context.youcom_adapter is None
        assert _RecordingAdapter.instances == [context.adapter]
        assert context.adapter.api_key is not None, (
            "the harness must inject the Tavily key via the explicit api_key seam"
        )
        assert context.adapter.api_key.get_secret_value() == "harness-tavily-key"
    finally:
        _close_after(context)

    assert context.adapter.closed is True
    assert context.http_client.closed is True


def test_tavily_scenario_without_harness_key_skips_before_fail_closed_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no harness key the Tavily scenario is skipped BEFORE any adapter is
    constructed, so the adapter's fail-closed raise can no longer surface as a
    Behave hook error during an offline run."""
    monkeypatch.setattr(environment, "TavilyAdapter", _FailClosedAdapter)

    context = _run_scenario(monkeypatch, ["live", "search"])
    scenario = context.scenario
    try:
        assert scenario.skipped is True
        assert "POLYWEB_TAVILY_API_KEY" in (scenario.skip_reason or "")
        assert getattr(context, "adapter", None) is None
        assert not hasattr(context, "loop"), "skip must precede event-loop setup"
        assert not hasattr(context, "http_client"), "skip must precede client setup"
    finally:
        _close_after(context)


def test_production_tavily_adapter_still_fails_closed_without_api_key() -> None:
    """Intentional Tavily replacement (PLAN 4.1, DTC 5.1): the explicit
    constructor builds the keyless public rail instead of failing closed."""
    from polyweb.models.provider_limits import AuthMode

    client = httpx.AsyncClient()
    adapter: TavilyAdapter | None = None
    try:
        adapter = TavilyAdapter(client, api_key=None)
        assert adapter.limit_auth_mode is AuthMode.KEYLESS
    finally:
        if adapter is not None:
            asyncio.new_event_loop().run_until_complete(adapter.aclose())
        asyncio.new_event_loop().run_until_complete(client.aclose())
