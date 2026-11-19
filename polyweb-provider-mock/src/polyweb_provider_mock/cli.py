"""``polyweb-mock``: the admin ("god mode") CLI of the provider mock.

The CLI writes the SQLite state database directly through
:class:`~polyweb_provider_mock.store.MockStore`, the same service layer that
the server reads on every request, so each change applies to the next
request without a restart. Results print as JSON.

Examples::

    polyweb-mock seed --reset
    polyweb-mock credits add tavily 500
    polyweb-mock account set keenable reset_day=17
    polyweb-mock fault add tavily --op search --kind rate_limit --probability 0.5 \\
        --count 10 --duration 10m
    polyweb-mock latency set tavily --ms 800 --jitter 200
    polyweb-mock scenario apply tavily-down
    polyweb-mock export-keys --format dotenv
"""

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from polyweb_provider_mock.admin import dotenv_lines
from polyweb_provider_mock.faults import FaultKind, FaultParams, FaultSpec, parse_duration
from polyweb_provider_mock.models import PriceRule
from polyweb_provider_mock.providers import discover, plugin
from polyweb_provider_mock.scenarios import apply_scenario, clear_scenarios, scenarios
from polyweb_provider_mock.settings import MockSettings
from polyweb_provider_mock.store import MockStore, NotFoundError

__all__ = ["build_parser", "main"]

Command = Callable[[argparse.Namespace, MockStore], Any]


def _decimal(text: str) -> Decimal:
    try:
        return Decimal(text)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from None


def _optional_int(text: str) -> int | None:
    return None if text.lower() in {"none", "off", "unlimited"} else int(text)


def _balance(text: str) -> Decimal | None:
    return None if text.lower() in {"none", "unlimited"} else _decimal(text)


def _plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    return value


def _emit(value: Any) -> None:
    if isinstance(value, str):
        sys.stdout.write(value)
        return
    print(json.dumps(_plain(value), indent=2, default=str))


# ------------------------------------------------------------------ commands


def _seed(args: argparse.Namespace, store: MockStore) -> Any:
    return store.seed(discover().values(), reset=args.reset)


def _reset(args: argparse.Namespace, store: MockStore) -> Any:
    store.reset()
    return {"status": "reset", "hint": "run `polyweb-mock seed` to restore the defaults"}


def _keys(args: argparse.Namespace, store: MockStore) -> Any:
    if args.action == "list":
        return store.keys(args.provider)
    if args.action == "create":
        return store.create_key(
            args.provider,
            plugin(args.provider).key_format,
            account_id=args.account,
            label=args.label,
            key=args.key,
            scopes=args.scope or (),
            env_var=args.env_var,
            credit_limit=args.limit,
        )
    if args.action == "revoke":
        return store.set_key_status(args.provider, args.key_or_label, "revoked")
    return store.set_key_status(args.provider, args.key_or_label, "active")


def _credits(args: argparse.Namespace, store: MockStore) -> Any:
    if args.action == "show":
        return store.accounts(args.provider)
    if args.action == "add" and args.prepaid:
        return store.add_prepaid(args.provider, args.amount, args.account)
    if args.action == "add":
        return store.add_credits(args.provider, args.amount, args.account)
    if args.action == "funding":
        return store.set_funding(
            args.provider, args.funding, args.account, overage_limit=args.overage_limit
        )
    return store.set_credits(args.provider, args.amount, args.account, used=args.used)


def _attribute(text: str) -> tuple[str, Any]:
    name, sep, raw = text.partition("=")
    if not sep or not name.strip():
        raise argparse.ArgumentTypeError(f"expected NAME=VALUE, not {text!r}")
    try:
        value: Any = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        value = raw
    return name.strip(), value


def _account(args: argparse.Namespace, store: MockStore) -> Any:
    if args.action == "show":
        return store.accounts(args.provider)
    plugin(args.provider)
    return store.set_account_attributes(args.provider, dict(args.attributes), args.account)


def _pricing(args: argparse.Namespace, store: MockStore) -> Any:
    if args.action == "show":
        return store.prices(args.provider)
    plugin(args.provider)
    return store.set_price(
        PriceRule(
            provider=args.provider,
            operation=args.operation,
            credits_per_unit=args.credits,
            usd_per_unit=args.usd,
            unit=args.unit,
            rule=args.rule,
        )
    )


def _keyless(args: argparse.Namespace, store: MockStore) -> Any:
    if args.action == "show":
        settings = store.keyless_settings()
        return [item for item in settings if args.provider in (None, item.provider)]
    plugin(args.provider)
    changes: dict[str, Any] = {"enabled": args.enabled}
    if args.per_day is not ...:
        changes["per_day"] = args.per_day
    if args.per_minute is not ...:
        changes["per_minute"] = args.per_minute
    return store.set_keyless(args.provider, **changes)


def _fault_spec(args: argparse.Namespace) -> FaultSpec:
    if args.provider != "*":
        plugin(args.provider)
    params = FaultParams(
        ms=args.ms,
        jitter_ms=args.jitter,
        seconds=args.seconds,
        status=args.status,
        message=args.message,
        retry_after=args.retry_after,
        retry_after_header=not args.no_retry_after_header,
        scope=args.scope,
        variant=args.variant,
    )
    return FaultSpec(
        provider=args.provider,
        operation=args.op,
        kind=FaultKind(args.kind),
        params=params,
        probability=args.probability,
        count=args.count,
        duration_seconds=None if args.duration is None else parse_duration(args.duration),
    )


def _fault(args: argparse.Namespace, store: MockStore) -> Any:
    if args.action == "list":
        return store.faults()
    if args.action == "add":
        return store.add_fault(_fault_spec(args))
    if args.action in {"enable", "disable"}:
        return store.set_fault_enabled(args.id, args.action == "enable")
    kind = None if args.kind is None else FaultKind(args.kind)
    removed = store.clear_faults(
        rule_id=args.id, provider=args.provider, scenario=args.scenario, kind=kind
    )
    return {"removed": removed}


def _latency(args: argparse.Namespace, store: MockStore) -> Any:
    if args.provider != "*":
        plugin(args.provider)
    if args.action == "clear":
        return store.set_latency(args.provider, 0, 0, operation=args.op) or {"latency": "cleared"}
    return store.set_latency(args.provider, args.ms, args.jitter, operation=args.op)


def _scenario(args: argparse.Namespace, store: MockStore) -> Any:
    names = discover()
    if args.action == "list":
        return [
            {"name": item.name, "description": item.description}
            for item in scenarios(names).values()
        ]
    if args.action == "apply":
        return apply_scenario(store, args.name, names)
    return {"removed": clear_scenarios(store, names, args.name)}


def _fixtures(args: argparse.Namespace, store: MockStore) -> Any:
    if args.action == "list":
        return store.fixtures(args.provider)
    if args.action == "delete":
        return {"deleted": store.delete_fixture(args.id)}
    if args.from_log is not None:
        return store.save_fixture_from_log(args.from_log, match_key=args.match_key)
    if args.provider is None or args.operation is None or args.match_key is None:
        raise ValueError("fixtures save --file needs PROVIDER OPERATION MATCH_KEY")
    plugin(args.provider)
    body = json.loads(Path(args.file).read_text(encoding="utf-8"))
    return store.save_fixture(
        args.provider, args.operation, args.match_key, body, status=args.status
    )


def _log(args: argparse.Namespace, store: MockStore) -> Any:
    return store.log_tail(args.provider, args.limit, with_bodies=args.bodies)


def _export(args: argparse.Namespace, store: MockStore) -> Any:
    if args.format == "json":
        return dict(store.export_keys())
    return dotenv_lines(store)


# -------------------------------------------------------------------- parser


def _keys_parser(groups: Any) -> None:
    keys = groups.add_parser("keys", help="list, create, revoke, or restore mock API keys")
    actions = keys.add_subparsers(dest="action", required=True)
    actions.add_parser("list").add_argument("--provider")
    create = actions.add_parser("create")
    create.add_argument("provider")
    create.add_argument("--account", help="account id (default: the provider's first account)")
    create.add_argument("--label")
    create.add_argument("--key", help="explicit key value (default: random in the real format)")
    create.add_argument("--scope", action="append", help="key scope, repeatable")
    create.add_argument("--env-var", help="variable name for export-keys")
    create.add_argument("--limit", type=_decimal, help="per-key credit limit")
    for action in ("revoke", "restore"):
        parser = actions.add_parser(action)
        parser.add_argument("provider")
        parser.add_argument("key_or_label")
    keys.set_defaults(handler=_keys)


def _credits_parser(groups: Any) -> None:
    credits = groups.add_parser("credits", help="show, add, or set account credits")
    actions = credits.add_subparsers(dest="action", required=True)
    actions.add_parser("show").add_argument("provider", nargs="?")
    add = actions.add_parser("add")
    add.add_argument("provider")
    add.add_argument("amount", type=_decimal)
    add.add_argument("--account")
    add.add_argument(
        "--prepaid",
        action="store_true",
        help="add one-time credit that never resets (spent after the grant)",
    )
    funding = actions.add_parser(
        "funding", help="prepaid (refused at zero) or postpaid (billed after use)"
    )
    funding.add_argument("provider")
    funding.add_argument("funding", choices=("prepaid", "postpaid"))
    funding.add_argument("--account")
    funding.add_argument("--overage-limit", type=_decimal, help="postpaid spend cap")
    put = actions.add_parser("set", help="set the remaining balance (or 'unlimited')")
    put.add_argument("provider")
    put.add_argument("amount", type=_balance)
    put.add_argument("--account")
    put.add_argument("--used", type=_decimal, help="also set the used credits")
    credits.set_defaults(handler=_credits)

    account = groups.add_parser("account", help="show accounts or set account attributes")
    actions = account.add_subparsers(dest="action", required=True)
    actions.add_parser("show").add_argument("provider", nargs="?")
    attrs = actions.add_parser(
        "set", help="merge NAME=VALUE attributes (JSON values; NAME= removes one)"
    )
    attrs.add_argument("provider")
    attrs.add_argument("attributes", nargs="+", type=_attribute, metavar="NAME=VALUE")
    attrs.add_argument("--account", help="account id (default: the provider's first account)")
    account.set_defaults(handler=_account)


def _pricing_parser(groups: Any) -> None:
    pricing = groups.add_parser("pricing", help="show or set operation prices")
    actions = pricing.add_subparsers(dest="action", required=True)
    actions.add_parser("show").add_argument("provider", nargs="?")
    put = actions.add_parser("set")
    put.add_argument("provider")
    put.add_argument("operation", help="priced operation, for example search.basic")
    put.add_argument("--credits", type=_decimal, required=True, help="credits per unit")
    put.add_argument("--usd", type=_decimal, help="USD per unit")
    put.add_argument("--unit", default="request")
    put.add_argument("--rule", choices=("per_unit", "accumulate"), default="per_unit")
    pricing.set_defaults(handler=_pricing)


def _keyless_parser(groups: Any) -> None:
    keyless = groups.add_parser("keyless", help="show or set keyless mode and its budget")
    actions = keyless.add_subparsers(dest="action", required=True)
    actions.add_parser("show").add_argument("provider", nargs="?")
    put = actions.add_parser("set")
    put.add_argument("provider")
    switch = put.add_mutually_exclusive_group()
    switch.add_argument("--enable", dest="enabled", action="store_true", default=None)
    switch.add_argument("--disable", dest="enabled", action="store_false")
    put.add_argument("--per-day", type=_optional_int, default=..., help="calls per UTC day")
    put.add_argument("--per-minute", type=_optional_int, default=..., help="calls per minute")
    keyless.set_defaults(handler=_keyless)


def _fault_parser(groups: Any) -> None:
    fault = groups.add_parser("fault", help="list, add, enable, disable, or clear fault rules")
    actions = fault.add_subparsers(dest="action", required=True)
    actions.add_parser("list")
    add = actions.add_parser("add")
    add.add_argument("provider", help="provider name or *")
    add.add_argument("--op", default="*", help="operation name or * (default)")
    add.add_argument("--kind", required=True, choices=[kind.value for kind in FaultKind])
    add.add_argument("--probability", type=float, default=1.0)
    add.add_argument("--count", type=int, help="fire at most this many times")
    add.add_argument("--duration", help="stop after this long, for example 10m")
    add.add_argument("--ms", type=float, help="latency milliseconds")
    add.add_argument("--jitter", type=float, help="latency jitter milliseconds")
    add.add_argument("--seconds", type=float, help="timeout hold seconds")
    add.add_argument("--status", type=int, help="HTTP status for http_error, outage, quota")
    add.add_argument("--retry-after", type=int, help="rate_limit Retry-After seconds")
    add.add_argument("--no-retry-after-header", action="store_true")
    add.add_argument("--scope", help="quota scope: account, key, paygo")
    add.add_argument(
        "--variant", choices=("invalid_json", "truncated", "wrong_content_type", "missing_field")
    )
    add.add_argument("--message", help="override the provider error message")
    for action in ("enable", "disable"):
        actions.add_parser(action).add_argument("id", type=int)
    clear = actions.add_parser("clear", help="remove matching rules (all without filters)")
    clear.add_argument("--id", type=int)
    clear.add_argument("--provider")
    clear.add_argument("--scenario")
    clear.add_argument("--kind", choices=[kind.value for kind in FaultKind])
    fault.set_defaults(handler=_fault)


def _latency_parser(groups: Any) -> None:
    latency = groups.add_parser("latency", help="set or clear standing latency")
    actions = latency.add_subparsers(dest="action", required=True)
    put = actions.add_parser("set")
    put.add_argument("provider", help="provider name or *")
    put.add_argument("--ms", type=float, required=True)
    put.add_argument("--jitter", type=float, default=0.0)
    put.add_argument("--op", default="*")
    clear = actions.add_parser("clear")
    clear.add_argument("provider")
    clear.add_argument("--op", default="*")
    latency.set_defaults(handler=_latency)


def _other_parsers(groups: Any) -> None:
    seed = groups.add_parser("seed", help="create the default accounts, keys, and prices")
    seed.add_argument("--reset", action="store_true", help="delete all state first")
    seed.set_defaults(handler=_seed)
    groups.add_parser("reset", help="delete all state").set_defaults(handler=_reset)

    scenario = groups.add_parser("scenario", help="list, apply, or clear preset scenarios")
    actions = scenario.add_subparsers(dest="action", required=True)
    actions.add_parser("list")
    actions.add_parser("apply").add_argument("name")
    actions.add_parser("clear").add_argument("name", nargs="?")
    scenario.set_defaults(handler=_scenario)

    fixtures = groups.add_parser("fixtures", help="list, save, or delete saved responses")
    actions = fixtures.add_subparsers(dest="action", required=True)
    actions.add_parser("list").add_argument("--provider")
    save = actions.add_parser("save")
    save.add_argument("provider", nargs="?")
    save.add_argument("operation", nargs="?")
    save.add_argument("match_key", nargs="?", help="normalized query or URL")
    source = save.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", help="JSON response body file")
    source.add_argument("--from-log", type=int, help="request log id")
    save.add_argument("--status", type=int, default=200)
    actions.add_parser("delete").add_argument("id", type=int)
    fixtures.set_defaults(handler=_fixtures)

    log = groups.add_parser("log", help="show the request log")
    actions = log.add_subparsers(dest="action", required=True)
    tail = actions.add_parser("tail")
    tail.add_argument("--provider")
    tail.add_argument("--limit", type=int, default=20)
    tail.add_argument("--bodies", action="store_true", help="include response bodies")
    log.set_defaults(handler=_log)

    export = groups.add_parser("export-keys", help="print the active mock keys")
    export.add_argument("--format", choices=("dotenv", "json"), default="dotenv")
    export.set_defaults(handler=_export)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="polyweb-mock", description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="state database (default: POLYWEB_PROVIDER_MOCK_DB or polyweb-provider-mock/mock.db)",
    )
    groups = parser.add_subparsers(dest="command", required=True)
    for build in (
        _other_parsers,
        _keys_parser,
        _credits_parser,
        _pricing_parser,
        _keyless_parser,
        _fault_parser,
        _latency_parser,
    ):
        build(groups)
    for found in discover().values():
        found.cli_commands(groups)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = MockStore(args.db or MockSettings.from_env().db_path)
    try:
        _emit(args.handler(args, store))
    except (KeyError, LookupError, NotFoundError, ValueError) as exc:
        message = exc.args[0] if isinstance(exc, KeyError) and exc.args else str(exc)
        print(f"polyweb-mock: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
