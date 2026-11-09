"""Routing-latency scenarios (@latency) never reach default adapter construction.

Offline ``@latency`` and opt-in ``@live @latency`` scenarios serve their own
adapters from their steps. ``before_scenario`` must take the offline early
return for both (no ``_adapter_for``, no Tavily live-key gate); ``@live
@latency`` gates each provider on its own harness key inside its steps. No
real credential and no network call is used here.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from polyweb.infrastructure.secrets import PROVIDER_ENV_VARS  # noqa: E402
from tests.bdd.features import environment  # noqa: E402


class _FakeScenario:
    """Behave scenario stand-in with feature-level tags and skip recording."""

    def __init__(self, tags: list[str], feature_tags: list[str]) -> None:
        self.tags = tags
        self.feature = SimpleNamespace(name="Polyweb routing latency", tags=feature_tags)
        self.effective_tags = {*tags, *feature_tags}
        self.skipped = False
        self.skip_reason: str | None = None

    def skip(self, reason: str | None = None) -> None:
        self.skipped = True
        self.skip_reason = reason

    def mark_skipped(self, reason: str | None = None) -> None:
        self.skip(reason)


def _forbid_adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("latency scenarios must not construct a default adapter")

    monkeypatch.setattr(environment, "_adapter_for", explode)


def _clear_harness_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_var in PROVIDER_ENV_VARS.values():
        monkeypatch.delenv(env_var, raising=False)


@pytest.mark.parametrize(
    "feature_tags",
    [["latency"], ["live", "latency"]],
    ids=["offline-latency", "live-latency"],
)
def test_latency_scenarios_take_the_offline_path_without_keys(
    monkeypatch: pytest.MonkeyPatch, feature_tags: list[str]
) -> None:
    """No harness keys: the scenario is not skipped by the environment, gets a
    loop and client, and no default (Tavily) adapter is constructed."""

    _clear_harness_keys(monkeypatch)
    _forbid_adapters(monkeypatch)
    context = SimpleNamespace()
    environment.before_all(context)
    scenario = _FakeScenario([], feature_tags)

    environment.before_scenario(context, scenario)
    try:
        assert scenario.skipped is False
        assert context.adapter is None
        assert context.youcom_adapter is None
        assert context.loop.is_closed() is False
    finally:
        environment.after_scenario(context, scenario)
    assert context.loop.is_closed()
    assert context.http_client.is_closed


def test_has_latency_tag_reads_feature_and_scenario_tags() -> None:
    feature_tagged = SimpleNamespace(tags=[], feature=SimpleNamespace(tags=["latency"]))
    scenario_tagged = SimpleNamespace(tags=["latency"])
    effective = SimpleNamespace(tags=[], effective_tags={"live", "latency"})
    untagged = SimpleNamespace(tags=["live"], feature=SimpleNamespace(tags=["search"]))

    assert environment._has_latency_tag(feature_tagged) is True
    assert environment._has_latency_tag(scenario_tagged) is True
    assert environment._has_latency_tag(effective) is True
    assert environment._has_latency_tag(untagged) is False
