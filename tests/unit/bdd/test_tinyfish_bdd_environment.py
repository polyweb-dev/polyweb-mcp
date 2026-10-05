"""Offline Tinyfish features keep the current lifecycle and avoid live adapters."""

from types import SimpleNamespace

import pytest

from tests.bdd.features import environment


def test_feature_level_tinyfish_tag_uses_offline_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    scenario = SimpleNamespace(
        tags=["search"], feature=SimpleNamespace(tags=["tinyfish", "offline"])
    )
    context = SimpleNamespace()

    def forbid_adapter(*args: object, **kwargs: object) -> None:
        raise AssertionError("offline Tinyfish must not construct a live provider")

    monkeypatch.setattr(environment, "_adapter_for", forbid_adapter)
    environment.before_scenario(context, scenario)
    try:
        assert context.adapter is None
        assert context.search_response is None
        assert context.last_error is None
        assert context.loop.is_closed() is False
    finally:
        environment.after_scenario(context, scenario)
    assert context.loop.is_closed()
    assert context.http_client.is_closed
