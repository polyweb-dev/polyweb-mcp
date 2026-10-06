"""Unit tests for the API launch path (P6, T10 parts).

The launch must read its port through the shared rule with no numeric
fallback. These tests mock the server runner, so no socket opens.
"""

from __future__ import annotations

import pytest

from freesearch.configuration.config import Settings


def _run_main(monkeypatch: pytest.MonkeyPatch, argv: list[str], settings: Settings) -> object:
    import freesearch.routers.api as api_module

    calls: list[dict[str, object]] = []

    def _fake_run(app: object, **kwargs: object) -> None:
        calls.append({"app": app, **kwargs})

    monkeypatch.setattr(api_module, "get_settings", lambda: settings)
    monkeypatch.setattr("uvicorn.run", _fake_run)
    api_module.main(argv)
    return calls


def test_main_stops_launch_when_port_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    import freesearch.routers.api as api_module

    monkeypatch.setattr(api_module, "get_settings", lambda: Settings(api_port=None, mcp_port=None))
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: None)

    with pytest.raises(ValueError, match="FREESEARCH_API_PORT"):
        api_module.main([])


def test_main_binds_the_configured_port(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _run_main(monkeypatch, [], Settings(api_port=8031, mcp_port=8030))

    assert len(calls) == 1
    assert calls[0]["port"] == 8031
    assert calls[0]["host"] == Settings(api_port=8031, mcp_port=8030).api_host


def test_main_explicit_port_wins_over_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _run_main(monkeypatch, ["--port", "9999"], Settings(api_port=8031, mcp_port=8030))

    assert len(calls) == 1
    assert calls[0]["port"] == 9999
