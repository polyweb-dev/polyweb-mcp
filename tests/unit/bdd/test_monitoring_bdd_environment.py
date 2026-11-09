"""BDD environment guards for feature-level offline monitoring scenarios."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from polyweb.infrastructure.secrets import PROVIDER_ENV_VARS

# ``features`` is an uninstalled namespace package at the repo root; make it
# importable regardless of pytest's sys.path manipulation.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.bdd.features import environment  # noqa: E402


class _FakeClient:
    """Stand-in for the factory-created HTTP client."""

    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _ForbiddenTavilyAdapter:
    """Construction raises so a monitoring guard must run first.

    It accepts the explicit ``api_key=``/``runner=`` constructor seam that
    ``environment._adapter_for`` passes, so a guard regression surfaces as this
    assertion instead of an unrelated ``TypeError`` from the double.
    """

    def __init__(self, client: object, *, api_key: object = None, runner: object = None) -> None:
        raise AssertionError("TavilyAdapter must not be constructed for monitoring")


def _clear_harness_provider_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every harness provider key from the process env for this test."""
    for env_var in PROVIDER_ENV_VARS.values():
        monkeypatch.delenv(env_var, raising=False)


def _feature_level_monitoring_scenario() -> SimpleNamespace:
    """Model Behave's inherited feature tag and its effective tag set."""
    return SimpleNamespace(
        tags=[],
        effective_tags={"monitoring"},
        feature=SimpleNamespace(tags=["monitoring"]),
    )


def test_before_scenario_skips_adapter_construction_for_feature_level_monitoring_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeClient()
    monkeypatch.setattr(environment, "create_async_client", lambda: fake_client)
    monkeypatch.setattr(environment, "TavilyAdapter", _ForbiddenTavilyAdapter)
    context = SimpleNamespace()

    try:
        environment.before_scenario(context, _feature_level_monitoring_scenario())
    finally:
        if getattr(context, "loop", None) is not None:
            environment.after_scenario(context, None)

    assert context.adapter is None


def test_has_monitoring_tag_reads_feature_tags_without_effective_tags() -> None:
    feature_tagged = SimpleNamespace(tags=[], feature=SimpleNamespace(tags=["monitoring"]))
    scenario_tagged = SimpleNamespace(tags=["monitoring"])
    untagged = SimpleNamespace(tags=[], feature=SimpleNamespace(tags=[]))

    assert environment._has_monitoring_tag(feature_tagged) is True
    assert environment._has_monitoring_tag(scenario_tagged) is True
    assert environment._has_monitoring_tag(untagged) is False


def test_before_scenario_needs_no_tavily_key_for_monitoring_feature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A monitoring scenario needs no provider key at all.

    The offline monitoring branch returns before the live missing-key gates, so
    with an empty environment the scenario still runs, still gets the shared
    client, and never constructs the Tavily default adapter. The harness reads
    the process env directly (``_harness_env_key``); the retired
    ``get_provider_secret_resolver`` seam must not be consulted.
    """
    _clear_harness_provider_keys(monkeypatch)
    fake_client = _FakeClient()
    monkeypatch.setattr(environment, "create_async_client", lambda: fake_client)
    monkeypatch.setattr(environment, "TavilyAdapter", _ForbiddenTavilyAdapter)
    context = SimpleNamespace()
    environment.before_all(context)
    scenario = _feature_level_monitoring_scenario()

    try:
        environment.before_scenario(context, scenario)
    finally:
        if getattr(context, "loop", None) is not None:
            environment.after_scenario(context, None)

    assert getattr(context, "adapter", None) is None
    assert context.has_tavily_key is False, "before_all must resolve the flag from the env"
    assert fake_client.closed is True, "the shared client must still be closed"
    assert not hasattr(environment, "get_provider_secret_resolver")
