"""BDD environment guard tests for offline control scenarios."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# ``features`` is a root namespace package; make it importable in isolation.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.bdd.features import environment  # noqa: E402


class _FakeClient:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _ForbiddenTavilyAdapter:
    """Construction raises: proves the offline control guard ran first.

    It accepts the explicit ``api_key=``/``runner=`` seam that
    ``environment._adapter_for`` now passes, so a guard regression surfaces as
    this assertion instead of an unrelated ``TypeError`` from the double.
    """

    def __init__(self, client: object, *, api_key: object = None, runner: object = None) -> None:
        raise AssertionError("TavilyAdapter must not be constructed for control scenarios")


def _feature_level_control_scenario() -> SimpleNamespace:
    return SimpleNamespace(
        tags=[],
        effective_tags={"control"},
        feature=SimpleNamespace(tags=["control"]),
    )


def test_before_scenario_skips_default_adapter_for_feature_level_control_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeClient()
    monkeypatch.setattr(environment, "create_async_client", lambda: fake_client)
    monkeypatch.setattr(environment, "TavilyAdapter", _ForbiddenTavilyAdapter)
    context = SimpleNamespace()

    try:
        environment.before_scenario(context, _feature_level_control_scenario())
    finally:
        if getattr(context, "loop", None) is not None:
            environment.after_scenario(context, None)

    assert context.adapter is None


def test_has_control_tag_reads_feature_and_scenario_tags() -> None:
    feature_tagged = SimpleNamespace(tags=[], feature=SimpleNamespace(tags=["control"]))
    scenario_tagged = SimpleNamespace(tags=["control"])
    untagged = SimpleNamespace(tags=[], feature=SimpleNamespace(tags=[]))

    assert environment._has_control_tag(feature_tagged) is True
    assert environment._has_control_tag(scenario_tagged) is True
    assert environment._has_control_tag(untagged) is False
