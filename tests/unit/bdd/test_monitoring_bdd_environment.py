"""BDD environment guards for feature-level offline monitoring scenarios."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from freesearch.adapters import tavily as tavily_module
from freesearch.infrastructure.secrets import ProviderName

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
    """Construction raises so a monitoring guard must run first."""

    def __init__(self, client: object) -> None:
        raise AssertionError("TavilyAdapter must not be constructed for monitoring")


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
    class _NoKeyResolver:
        def get(self, provider: ProviderName) -> None:
            return None

    fake_client = _FakeClient()
    monkeypatch.setattr(environment, "get_provider_secret_resolver", lambda: _NoKeyResolver())
    monkeypatch.setattr(tavily_module, "get_provider_secret_resolver", lambda: _NoKeyResolver())
    monkeypatch.setattr(environment, "create_async_client", lambda: fake_client)
    context = SimpleNamespace()
    environment.before_all(context)

    try:
        environment.before_scenario(context, _feature_level_monitoring_scenario())
    finally:
        if getattr(context, "loop", None) is not None:
            environment.after_scenario(context, None)

    assert getattr(context, "adapter", None) is None
