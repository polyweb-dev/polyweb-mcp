"""Unit tests for the REST launch path (port resolution).

Route planning and single-attempt dispatch moved out of ``routers.api`` into
the shared :class:`polyweb.services.execution.ExecutionService`. Their
behavioral coverage now lives in
``tests/integration/services/test_execution_routing.py`` (the five original
router case names, search/fetch/policy matrices, read budget and tolerant reads)
and ``test_a2_execution_regressions.py`` (same-provider pin and fanout); this
module keeps the transport launch seam only.
"""

from __future__ import annotations

import pytest

from polyweb.configuration.config import Settings


# --- Merged from release/wt_3: API launch path (port handling) ---
def _isolate_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """main() runs the pre-start database check: point it at a fresh temp path."""

    import tempfile
    from pathlib import Path
    from uuid import uuid4

    from polyweb.configuration.config import get_settings

    target = Path(tempfile.gettempdir()) / f"polyweb-main-{uuid4().hex}" / "main.db"
    monkeypatch.setenv("POLYWEB_DB", str(target))
    get_settings.cache_clear()


def _run_main(monkeypatch: pytest.MonkeyPatch, argv: list[str], settings: Settings) -> object:
    import polyweb.routers.api as api_module

    _isolate_database(monkeypatch)

    calls: list[dict[str, object]] = []

    def _fake_run(app: object, **kwargs: object) -> None:
        calls.append({"app": app, **kwargs})

    monkeypatch.setattr(api_module, "get_settings", lambda: settings)
    monkeypatch.setattr("uvicorn.run", _fake_run)
    api_module.main(argv)
    return calls


def test_main_stops_launch_when_port_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    import polyweb.routers.api as api_module

    _isolate_database(monkeypatch)

    monkeypatch.setattr(api_module, "get_settings", lambda: Settings(api_port=None, mcp_port=None))
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: None)

    with pytest.raises(ValueError, match="POLYWEB_API_PORT"):
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
