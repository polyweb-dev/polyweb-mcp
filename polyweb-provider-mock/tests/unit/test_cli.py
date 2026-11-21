"""The ``polyweb-mock`` admin CLI against a temporary state database."""

import json
from pathlib import Path
from typing import Any

import pytest

from polyweb_provider_mock.cli import main
from polyweb_provider_mock.faults import FaultKind
from polyweb_provider_mock.providers import discover
from polyweb_provider_mock.store import MockStore


class _Cli:
    def __init__(self, db: Path, capsys: pytest.CaptureFixture[str]) -> None:
        self.db = db
        self.capsys = capsys

    def __call__(self, *argv: str) -> Any:
        code = main(["--db", str(self.db), *argv])
        out, err = self.capsys.readouterr()
        assert code == 0, err
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return out

    def fails(self, *argv: str) -> str:
        assert main(["--db", str(self.db), *argv]) == 1
        return self.capsys.readouterr().err


def _seeded_counts() -> dict[str, int]:
    return {name: len(item.default_seed().keys) for name, item in discover().items()}


@pytest.fixture
def cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> _Cli:
    runner = _Cli(tmp_path / "mock.db", capsys)
    seeded = runner("seed")
    assert seeded == _seeded_counts() and seeded["tavily"] == 2
    return runner


def test_keys_create_list_revoke_restore(cli: _Cli) -> None:
    created = cli("keys", "create", "tavily", "--label", "ci", "--scope", "search")
    assert created["key"].startswith("tvly-dev-mock") and created["scopes"] == ["search"]
    assert [key["label"] for key in cli("keys", "list", "--provider", "tavily")] == [
        "default",
        "secondary",
        "ci",
    ]
    assert cli("keys", "revoke", "tavily", "ci")["status"] == "revoked"
    assert cli("keys", "restore", "tavily", created["key"])["status"] == "active"
    assert "unknown provider" in cli.fails("keys", "create", "nobody")


def test_credits_pricing_and_keyless(cli: _Cli) -> None:
    assert cli("credits", "add", "tavily", "250")["credit_limit"] == "1250"
    assert cli("credits", "set", "tavily", "0")["credit_limit"] == "0"
    assert cli("credits", "set", "tavily", "unlimited")["credit_limit"] is None
    assert cli("credits", "show", "tavily")[0]["plan"] == "Researcher"

    price = cli("pricing", "set", "tavily", "search.basic", "--credits", "3", "--usd", "0.03")
    assert (price["credits_per_unit"], price["usd_per_unit"]) == ("3", "0.03")
    assert {row["operation"] for row in cli("pricing", "show", "tavily")} >= {"search.basic"}

    setting = cli("keyless", "set", "tavily", "--disable", "--per-minute", "5")
    assert setting == {"provider": "tavily", "enabled": False, "per_day": 500, "per_minute": 5}
    assert cli("keyless", "set", "tavily", "--enable", "--per-day", "none")["per_day"] is None


def test_account_show_and_attribute_set(cli: _Cli) -> None:
    account = cli("account", "set", "keenable", "reset_day=17", "plan_note=beta", "free_allowance=")
    assert account["attributes"] == {"reset_day": 17, "plan_note": "beta"}
    assert account["period_start"].split("T")[0].endswith("-17")
    shown = cli("account", "show", "tinyfish")
    assert [item["id"] for item in shown] == ["tinyfish-personal"]
    assert "reset_day must be 1..31" in cli.fails("account", "set", "keenable", "reset_day=40")
    assert "unknown provider" in cli.fails("account", "set", "nobody", "x=1")


def test_fault_add_list_clear(cli: _Cli) -> None:
    rule = cli(
        "fault",
        "add",
        "tavily",
        "--op",
        "search",
        "--kind",
        "rate_limit",
        "--probability",
        "0.5",
        "--count",
        "10",
        "--duration",
        "10m",
        "--retry-after",
        "30",
    )
    assert (rule["probability"], rule["remaining"], rule["params"]["retry_after"]) == (0.5, 10, 30)
    assert rule["expires_at"] is not None
    assert cli("fault", "disable", str(rule["id"]))["enabled"] is False
    cli("fault", "add", "*", "--kind", "malformed", "--variant", "truncated")
    assert [item["kind"] for item in cli("fault", "list")] == ["rate_limit", "malformed"]
    assert cli("fault", "clear", "--kind", "malformed") == {"removed": 1}
    assert cli("fault", "clear") == {"removed": 1}
    assert "invalid duration" in cli.fails(
        "fault", "add", "tavily", "--kind", "outage", "--duration", "x"
    )


def test_latency_and_scenarios(cli: _Cli, tmp_path: Path) -> None:
    rule = cli("latency", "set", "tavily", "--ms", "800", "--jitter", "200")
    assert (rule["kind"], rule["params"]["ms"], rule["params"]["jitter_ms"]) == (
        "latency",
        800.0,
        200.0,
    )
    names = {item["name"] for item in cli("scenario", "list")}
    assert names >= {
        "all-providers-down",
        "tavily-down",
        "slow-network",
        "flaky-10pct",
        "credits-exhausted",
        "rate-limit-storm",
    }
    assert len(cli("scenario", "apply", "flaky-10pct")) == 3
    cli("scenario", "apply", "tavily-down")
    assert cli("scenario", "clear", "tavily-down") == {"removed": 1}
    assert cli("scenario", "clear") == {"removed": 3}
    assert cli("latency", "clear", "tavily") == {"latency": "cleared"}
    assert MockStore(tmp_path / "mock.db").faults() == []
    assert "unknown scenario" in cli.fails("scenario", "apply", "nope")


def test_fixtures_from_file_and_log(cli: _Cli, tmp_path: Path) -> None:
    body = tmp_path / "body.json"
    body.write_text(json.dumps({"query": "q", "results": []}), encoding="utf-8")
    saved = cli("fixtures", "save", "tavily", "search", "q", "--file", str(body))
    assert saved["body"] == {"query": "q", "results": []}

    store = MockStore(tmp_path / "mock.db")
    log_id = store.log_request(
        provider="tavily",
        operation="search",
        method="POST",
        path="/search",
        key_label="default",
        status=200,
        latency_ms=2.0,
        fault=None,
        match_key="logged query",
        summary={"method": "POST"},
        response_body='{"query": "logged query", "results": []}',
    )
    from_log = cli("fixtures", "save", "--from-log", str(log_id))
    assert from_log["match_key"] == "logged query"
    assert len(cli("fixtures", "list", "--provider", "tavily")) == 2
    assert cli("fixtures", "delete", str(saved["id"])) == {"deleted": True}
    assert cli("log", "tail", "--provider", "tavily")[0]["response_body"] is None
    assert cli("log", "tail", "--bodies")[0]["response_body"].startswith("{")


def test_export_keys_and_reset(cli: _Cli) -> None:
    dotenv = cli("export-keys", "--format", "dotenv")
    lines = dotenv.splitlines()
    assert any(line.startswith("POLYWEB_TAVILY_API_KEY=tvly-dev-mock") for line in lines)
    assert dotenv.endswith("\n") and lines == sorted(lines)
    names = list(cli("export-keys", "--format", "json"))
    assert "POLYWEB_TAVILY_API_KEY" in names
    assert names == [line.split("=", 1)[0] for line in lines]
    cli("reset")
    assert cli("keys", "list") == []
    assert cli("seed", "--reset") == _seeded_counts()


def test_fault_kinds_cover_the_cli_choices() -> None:
    assert {kind.value for kind in FaultKind} == {
        "latency",
        "timeout",
        "http_error",
        "outage",
        "rate_limit",
        "quota_exhausted",
        "auth_invalid",
        "malformed",
        "connection_drop",
    }
