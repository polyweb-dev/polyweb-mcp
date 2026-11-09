"""Offline contract checks for the Exa live BDD step definitions."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from polyweb.adapters.exa import ExaAdapter
from polyweb.infrastructure import http as polyweb_http

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.bdd.features.steps import exa_steps  # noqa: E402


class _FakeSDKClient:
    """AsyncExa seam: the adapter must be able to close it."""

    async def aclose(self) -> None:
        pass


class _FakeSDK:
    """AsyncExa stand-in avoiding the resolver-backed construction path."""

    client = _FakeSDKClient()


def _exa_adapter() -> ExaAdapter:
    """A real ExaAdapter with the SDK seam injected: no resolver, no network."""
    return ExaAdapter(sdk_client=_FakeSDK())


def test_step_given_exa_adapter_passes_for_valid_adapter() -> None:
    """A keyed context holding a real ExaAdapter must satisfy the step."""
    adapter = _exa_adapter()
    try:
        context = SimpleNamespace(has_exa_key=True, adapter=adapter)

        exa_steps.step_given_exa_adapter(context)
    finally:
        asyncio.run(adapter.aclose())


def test_step_given_exa_adapter_fails_without_exa_key() -> None:
    """A keyless context must be rejected before the adapter check."""
    adapter = _exa_adapter()
    try:
        context = SimpleNamespace(has_exa_key=False, adapter=adapter)

        with pytest.raises(AssertionError, match="POLYWEB_EXA_API_KEY is not configured"):
            exa_steps.step_given_exa_adapter(context)
    finally:
        asyncio.run(adapter.aclose())


def test_step_given_exa_adapter_rejects_non_exa_adapter() -> None:
    """A keyed context holding the wrong adapter must fail the isinstance check."""
    context = SimpleNamespace(has_exa_key=True, adapter=object())

    with pytest.raises(AssertionError, match="Exa adapter was not initialized"):
        exa_steps.step_given_exa_adapter(context)


def test_missing_exa_key_skips_live_scenario_before_adapter_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A keyless live Exa scenario must not construct an adapter or reveal a key."""
    from tests.bdd.features import environment

    factory_called = False

    def fake_factory() -> object:
        nonlocal factory_called
        factory_called = True
        return object()

    monkeypatch.setattr(polyweb_http, "create_async_client", fake_factory)
    monkeypatch.setattr(environment, "create_async_client", fake_factory)
    scenario = SimpleNamespace(feature=SimpleNamespace(name="Exa Provider Adapter Integration"))
    scenario.skip = lambda reason: setattr(scenario, "skip_reason", reason)
    context = SimpleNamespace(has_exa_key=False)

    environment.before_scenario(context, scenario)

    assert not factory_called
    assert "POLYWEB_EXA_API_KEY" in scenario.skip_reason
    assert "sk-" not in scenario.skip_reason
