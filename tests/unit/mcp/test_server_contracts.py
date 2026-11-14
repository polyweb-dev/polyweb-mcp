"""MCP startup, schema and trace failure contracts."""

from __future__ import annotations

import json
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import SecretStr

import polyweb.mcp.server as mcp_server
from polyweb.infrastructure.observability import NO_OP_OBSERVABILITY
from polyweb.models.contracts import FetchRequest, SearchRequest
from polyweb.services.execution_forward import ExecutionForwardError


@pytest.mark.parametrize("transport", ["stdio", "streamable-http"])
@pytest.mark.parametrize(
    "authority,standalone", [(None, False), (None, True), ("http://authority", False)]
)
def test_main_requires_execution_backend(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    transport: str,
    authority: str | None,
    standalone: bool,
) -> None:
    settings = mcp_server.get_settings().model_copy(
        update={"execution_authority_url": authority, "execution_mcp_standalone": standalone}
    )
    monkeypatch.setattr(mcp_server, "get_settings", lambda: settings)
    reset_check = MagicMock()
    monkeypatch.setattr(mcp_server, "exit_if_database_reset_required", reset_check)
    monkeypatch.setattr(mcp_server, "resolve_database_path", lambda _: None)
    monkeypatch.setattr(mcp_server, "AuthService", lambda _: object())
    runner = AsyncMock()
    monkeypatch.setattr(mcp_server, "run_stdio_server", runner)
    monkeypatch.setattr(mcp_server, "run_http_server", runner)
    if authority is None and not standalone:
        with pytest.raises(SystemExit) as exited:
            mcp_server.main(["--transport", transport])
        assert exited.value.code == 1
        stderr = capsys.readouterr().err
        assert "POLYWEB_EXECUTION_AUTHORITY_URL" in stderr
        assert "POLYWEB_EXECUTION_MCP_STANDALONE" in stderr
        # A database needing a reset is reported before the execution config.
        reset_check.assert_called_once()
        runner.assert_not_awaited()
    else:
        mcp_server.main(["--transport", transport])
        runner.assert_awaited_once()


def _contains_ref(value: Any) -> bool:
    if isinstance(value, dict):
        return "$ref" in value or any(_contains_ref(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_ref(item) for item in value)
    return False


async def test_advertised_tool_schemas_are_fully_inlined() -> None:
    server = mcp_server.create_server([])
    tools = {tool.name: tool for tool in await server.list_tools()}
    for name, field in (("search", "query"), ("fetch", "url")):
        schema = tools[name].inputSchema
        assert not _contains_ref(schema)
        request = schema["properties"]["request"]
        assert {field, "routing", "providerOptions"} <= request["properties"].keys()
        assert request["additionalProperties"] is False
        # Descriptions are dedented so clients do not see docstring indentation.
        description = tools[name].description or ""
        assert not any(line.startswith(" ") for line in description.splitlines())
    # FastMCP's argument validator remains independent of the advertised schema.
    for name, invalid in (
        ("search", {"query": "x", "provider": "keenable"}),
        ("fetch", {"url": "https://example.com", "recency": "day"}),
    ):
        with pytest.raises(ToolError, match=r"extra_forbidden|Extra inputs"):
            await server.call_tool(name, {"request": invalid})


async def test_tool_description_examples_validate() -> None:
    server = mcp_server.create_server([])
    tools = {tool.name: tool.description or "" for tool in await server.list_tools()}
    SearchRequest.model_validate({"query": "weather"})
    SearchRequest.model_validate(
        {"query": "weather", "routing": {"mode": "require", "providers": ["keenable"]}}
    )
    SearchRequest.model_validate(
        {"query": "weather", "providerOptions": {"tavily": {"time_range": "week"}}}
    )
    SearchRequest.model_validate(
        {"query": "weather", "providerOptions": {"tinyfish": {"recency_minutes": 60}}}
    )
    FetchRequest.model_validate({"url": "https://example.com"})
    # The examples validated above are the ones the descriptions advertise.
    assert '"time_range": "week"' in tools["search"]
    assert '"recency_minutes": 60' in tools["search"]
    assert '"providers": ["keenable"]' in tools["search"]
    assert '{"url": "https://example.com"}' in tools["fetch"]


def test_inline_schema_refs_preserves_siblings_and_nullable_unions() -> None:
    schema = {
        "type": "object",
        "properties": {
            "mode": {"$ref": "#/$defs/Mode", "default": "auto", "description": "routing"},
            "maybe": {"anyOf": [{"$ref": "#/$defs/Mode"}, {"type": "null"}]},
        },
        "$defs": {"Mode": {"enum": ["auto", "require"], "type": "string", "description": "def"}},
    }
    inlined = mcp_server._inline_schema_refs(schema)
    assert "$defs" not in inlined
    assert "$ref" not in json.dumps(inlined)
    assert inlined["properties"]["mode"] == {
        "enum": ["auto", "require"],
        "type": "string",
        "description": "routing",
        "default": "auto",
    }
    assert inlined["properties"]["maybe"]["anyOf"][1] == {"type": "null"}
    assert inlined["properties"]["maybe"]["anyOf"][0]["enum"] == ["auto", "require"]


@pytest.mark.parametrize(
    "schema",
    [
        {
            "$ref": "#/$defs/Node",
            "$defs": {"Node": {"properties": {"next": {"$ref": "#/$defs/Node"}}}},
        },
        {"properties": {"x": {"$ref": "#/$defs/Missing"}}, "$defs": {}},
        {"properties": {"x": {"$ref": "https://example.com/schema"}}},
    ],
    ids=["recursive", "missing", "remote"],
)
def test_inline_schema_refs_rejects_unsupported_refs(schema: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        mcp_server._inline_schema_refs(schema)


async def test_tool_root_flushes_after_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    flush = AsyncMock()
    monkeypatch.setattr(mcp_server, "flush_traces", flush)
    monkeypatch.setattr(mcp_server, "bind_execution_attribution", lambda _: None)
    monkeypatch.setattr(mcp_server, "bind_trace_capture", lambda _: None)
    error = ValueError("tool failure")
    with pytest.raises(ValueError) as caught:
        async with mcp_server._tool_root(
            NO_OP_OBSERVABILITY,
            "test",
            {},
            attribution=cast(Any, None),
            trace_policy=cast(Any, None),
        ):
            raise error
    assert caught.value is error
    flush.assert_awaited_once_with(NO_OP_OBSERVABILITY)


async def test_tool_root_flushes_after_success(monkeypatch: pytest.MonkeyPatch) -> None:
    flush = AsyncMock()
    monkeypatch.setattr(mcp_server, "flush_traces", flush)
    monkeypatch.setattr(mcp_server, "bind_execution_attribution", lambda _: None)
    monkeypatch.setattr(mcp_server, "bind_trace_capture", lambda _: None)
    async with mcp_server._tool_root(
        NO_OP_OBSERVABILITY,
        "test",
        {},
        attribution=cast(Any, None),
        trace_policy=cast(Any, None),
    ):
        pass
    flush.assert_awaited_once_with(NO_OP_OBSERVABILITY)


async def test_forward_failure_logs_and_keeps_generic_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(mcp_server, "flush_traces", AsyncMock())
    monkeypatch.setattr(mcp_server, "bind_execution_attribution", lambda _: None)
    monkeypatch.setattr(mcp_server, "bind_trace_capture", lambda _: None)
    failure = ExecutionForwardError(
        "execution is temporarily unavailable", category="authority_unavailable"
    )
    failure.__cause__ = httpx.ConnectError("connection refused")
    forwarder = MagicMock()
    forwarder.search = AsyncMock(side_effect=failure)
    state = cast(
        Any, {"forwarder": forwarder, "execution": None, "observability": NO_OP_OBSERVABILITY}
    )
    with (
        caplog.at_level("WARNING"),
        pytest.raises(RuntimeError, match=r"^execution is temporarily unavailable$"),
    ):
        await mcp_server._tool_body(
            state,
            SearchRequest(query="test"),
            root_name="test",
            attribution=cast(Any, None),
            trace_policy=cast(Any, None),
            context=cast(Any, None),
            operation="search",
            credential=SecretStr("pw_secret_value"),
        )
    assert "category=authority_unavailable" in caplog.text
    assert "cause=ConnectError" in caplog.text
    assert "pw_secret_value" not in caplog.text


async def test_missing_backend_logs_and_keeps_generic_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    state = cast(Any, {"forwarder": None, "execution": None})
    with (
        caplog.at_level("ERROR"),
        pytest.raises(RuntimeError, match=r"^execution is temporarily unavailable$"),
    ):
        await mcp_server._tool_body(
            state,
            SearchRequest(query="test"),
            root_name="test",
            attribution=cast(Any, None),
            trace_policy=cast(Any, None),
            context=cast(Any, None),
            operation="search",
            credential=None,
        )
    assert "no forwarder or local execution backend" in caplog.text
