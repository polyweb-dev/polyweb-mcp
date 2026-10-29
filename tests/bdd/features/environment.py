"""Behave environment hooks for FreeSearch BDD test execution."""

import asyncio
import gc
import os
import time
from collections.abc import Iterable
from contextlib import suppress
from typing import Any

import httpx  # noqa: F401  # kept: locked BDD tests monkeypatch environment.httpx.AsyncClient
from pydantic import SecretStr

from freesearch.adapters.brave import BraveAdapter
from freesearch.adapters.exa import ExaAdapter
from freesearch.adapters.firecrawl import FirecrawlAdapter
from freesearch.adapters.keenable import KeenableAdapter
from freesearch.adapters.parallel import ParallelAdapter
from freesearch.adapters.tavily import TavilyAdapter
from freesearch.infrastructure.http import create_async_client
from freesearch.infrastructure.secrets import PROVIDER_ENV_VARS, ProviderName

_LIVE_GATE = "FREESEARCH_RUN_LIVE"


def _harness_env_key(provider: ProviderName) -> str | None:
    """Read the operator's process env directly (harness-only live-gate).

    This is explicitly NOT production resolution: vault-only production code
    never reads ``FREESEARCH_*`` at runtime. The harness reads the env only
    to decide whether a ``@live`` scenario can run and to inject the key
    explicitly via the adapter ``api_key`` seam.
    """

    return os.environ.get(PROVIDER_ENV_VARS[provider])


def before_all(context: Any) -> None:
    """Verify provider secrets availability before running feature suites."""
    context.has_tavily_key = _harness_env_key(ProviderName.TAVILY) is not None
    context.has_brave_key = _harness_env_key(ProviderName.BRAVE) is not None
    context.has_exa_key = _harness_env_key(ProviderName.EXA) is not None
    context.has_firecrawl_key = _harness_env_key(ProviderName.FIRECRAWL) is not None
    context.has_parallel_key = _harness_env_key(ProviderName.PARALLEL) is not None
    context.has_youcom_key = _harness_env_key(ProviderName.YOU) is not None
    context.has_keenable_key = _harness_env_key(ProviderName.KEENABLE) is not None


def before_scenario(context: Any, scenario: Any) -> None:
    """Set up async event loop, HTTP client, and provider adapter per scenario.

    The ordering below is a contract, cheapest and safest first:

    1. Offline quota/monitoring/control/fanout scenarios win over provider tags:
       they return before any live gate or live adapter construction, so the
       offline path never constructs live adapters. Live provider quota
       scenarios (``@live @quota``) are exempted so they fall through to live
       adapter construction and exercise the real vendor quota endpoints.
       Routing-latency scenarios (``@latency``, offline and ``@live``) also
       take this path: they serve their own adapters from their steps, and
       ``@live @latency`` gates each provider on its own harness key there.
    2. A ``@live @keenable`` scenario runs only when ``FREESEARCH_RUN_LIVE=1``;
       otherwise it is skipped before any resource setup, keeping offline BDD
       runs network-safe (Keenable is keyless, so no key check can gate it).
    3. Every live provider missing-key gate runs BEFORE the event loop and HTTP
       client are created, so a skipped live scenario allocates nothing: no
       event loop, no HTTP client, no adapter. Tavily (the ``_adapter_for``
       default) and Firecrawl are gated here too, so an offline run with no
       harness keys skips them instead of failing closed at construction.
    4. Only then are the loop, the client, and the tag-selected adapter built.

    The gates read only the boolean ``context.has_*_key`` flags that
    ``before_all`` resolved from the harness env; key material never enters a
    skip reason.
    """
    if (
        _has_monitoring_tag(scenario)
        or _has_control_tag(scenario)
        or _has_fanout_tag(scenario)
        or _has_limits_tag(scenario)
        or _has_users_tag(scenario)
        or _has_latency_tag(scenario)
        or (_has_quota_tag(scenario) and not _has_live_tag(scenario))
        or (_has_tinyfish_tag(scenario) and not _has_live_tag(scenario))
    ):
        context.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(context.loop)
        context.http_client = create_async_client()
        context.adapter = None
        context.youcom_adapter = None
        context.search_response = None
        context.fetch_response = None
        context.quota_snapshot = None
        context.last_error = None
        return
    if _has_keenable_tag(scenario) and os.environ.get(_LIVE_GATE) != "1":
        scenario.mark_skipped(f"live Keenable scenario requires {_LIVE_GATE}=1")
        return
    if _has_keenable_keyed_tag(scenario) and os.environ.get(_LIVE_GATE) != "1":
        scenario.mark_skipped(f"live Keenable scenario requires {_LIVE_GATE}=1")
        return
    if _is_exa_scenario(scenario) and not context.has_exa_key:
        scenario.skip("FREESEARCH_EXA_API_KEY is not configured")
        return
    missing_key_reason = _missing_live_key_reason(context, scenario)
    if missing_key_reason is not None:
        scenario.skip(reason=missing_key_reason)
        return
    context.loop = asyncio.new_event_loop()
    asyncio.set_event_loop(context.loop)
    context.http_client = create_async_client()
    context.adapter = None
    context.youcom_adapter = None
    # Offline scenarios supply their own adapters and repositories in their steps
    # (the early return above keeps them away from default provider construction
    # and any live network call), and You.com scenarios were gated above.
    if _has_youcom_tag(scenario):
        from freesearch.adapters.youcom import YoucomAdapter

        context.youcom_adapter = YoucomAdapter(
            context.http_client, api_key=_explicit_api_key(ProviderName.YOU)
        )
    else:
        context.adapter = _adapter_for(context.http_client, scenario)
    context.search_response = None
    context.fetch_response = None
    context.quota_snapshot = None
    context.last_error = None


def _explicit_api_key(provider: ProviderName) -> SecretStr | None:
    """Build the explicit adapter key from the harness env (never a resolver)."""

    raw = _harness_env_key(provider)
    return SecretStr(raw) if raw else None


def _adapter_for(client: Any, scenario: Any) -> Any:
    """Build the provider adapter declared by the live feature or scenario tags.

    Keys come only from the harness env via the explicit ``api_key``
    constructor seam; production resolution is never consulted.
    """
    if _has_parallel_tag(scenario):
        return ParallelAdapter(client, api_key=_explicit_api_key(ProviderName.PARALLEL))
    if _has_firecrawl_tag(scenario):
        return FirecrawlAdapter(client, api_key=_explicit_api_key(ProviderName.FIRECRAWL))
    if _has_keenable_tag(scenario) or _has_keenable_keyed_tag(scenario):
        return KeenableAdapter(client, api_key=_explicit_api_key(ProviderName.KEENABLE))
    if _has_brave_tag(scenario):
        return BraveAdapter(client, api_key=_explicit_api_key(ProviderName.BRAVE))
    if _is_exa_scenario(scenario):
        return ExaAdapter(client, api_key=_explicit_api_key(ProviderName.EXA))
    return TavilyAdapter(client, api_key=_explicit_api_key(ProviderName.TAVILY))


def _absent_key_reason(context: Any, flag: str, provider: ProviderName, label: str) -> str | None:
    """Return the missing-key skip reason for ``flag``, or None when the key is set.

    The reason names the env var (never any key material) so an operator can see
    directly which harness key is missing.
    """
    if getattr(context, flag, True):
        return None
    return (
        f"{PROVIDER_ENV_VARS[provider]} is not set "
        "(harness live-gate reads the process env only). "
        f"{label} live BDD scenarios are skipped without a harness env key."
    )


def _missing_live_key_reason(context: Any, scenario: Any) -> str | None:
    """Return the skip reason when the scenario's harness provider key is absent.

    Ordered like ``_adapter_for``'s selection so the reason always names the env
    var the adapter about to be constructed would consume. Exa is handled by the
    caller (it is identified by feature name, not by a tag). A ``context`` flag
    that was never set counts as "not gated": duck-typed scenario doubles that
    never ran ``before_all`` keep their previous construction behaviour, while a
    real Behave run always resolves the flags in ``before_all``.
    """
    if _has_youcom_tag(scenario):
        return _absent_key_reason(context, "has_youcom_key", ProviderName.YOU, "You.com")
    if _has_parallel_tag(scenario):
        return _absent_key_reason(context, "has_parallel_key", ProviderName.PARALLEL, "Parallel")
    if _has_firecrawl_tag(scenario):
        return _absent_key_reason(context, "has_firecrawl_key", ProviderName.FIRECRAWL, "Firecrawl")
    if _has_keenable_keyed_tag(scenario):
        return _absent_key_reason(
            context, "has_keenable_key", ProviderName.KEENABLE, "Keenable keyed"
        )
    if _has_brave_tag(scenario):
        return _absent_key_reason(context, "has_brave_key", ProviderName.BRAVE, "Brave")
    if _is_tavily_scenario(scenario):
        return _absent_key_reason(context, "has_tavily_key", ProviderName.TAVILY, "Tavily")
    return None


def _is_exa_scenario(scenario: Any) -> bool:
    """Identify scenarios declared by the Exa live feature."""
    return getattr(getattr(scenario, "feature", None), "name", "").startswith("Exa")


def _is_tavily_scenario(scenario: Any) -> bool:
    """Return True exactly when a live scenario falls through to Tavily.

    Tavily live scenarios (features/tavily.feature ``@live @search``/``@fetch``/
    ``@quota``) carry no provider tag, so a tag check alone cannot gate them.
    Instead, for a ``@live`` scenario this predicate is the exact complement of
    every other provider selection in ``_adapter_for`` - parallel, firecrawl,
    keenable, keenable-keyed, brave - plus the Exa feature check and the
    separately gated ``@youcom`` path.

    The ``@live`` requirement is what keeps the gate live-only: an ordinary
    untagged scenario (any offline BDD step that carries no provider tag) must
    still get its default adapter constructed rather than being skipped for a
    missing harness key.
    """
    if not _has_live_tag(scenario):
        return False
    return not (
        _has_parallel_tag(scenario)
        or _has_firecrawl_tag(scenario)
        or _has_keenable_tag(scenario)
        or _has_keenable_keyed_tag(scenario)
        or _has_brave_tag(scenario)
        or _is_exa_scenario(scenario)
        or _has_youcom_tag(scenario)
    )


def after_scenario(context: Any, scenario: Any) -> None:
    """Close every client/session before disposing and deleting its temporary DB."""
    loop = getattr(context, "loop", None)
    if loop is not None:
        from freesearch.mcp.server import shutdown_injected_observability

        for session, server in reversed(getattr(context, "_bdd_mcp_sessions", [])):
            loop.run_until_complete(session.__aexit__(None, None, None))
            loop.run_until_complete(shutdown_injected_observability(server))
        for case in reversed(getattr(context, "_bdd_oauth_cases", [])):
            loop.run_until_complete(case.close())
    for name in ("monitor_client", "test_client", "client", "otel_client", "enc_client"):
        client = getattr(context, name, None)
        if client is not None and callable(getattr(client, "__exit__", None)):
            with suppress(Exception):
                client.__exit__(None, None, None)
    repository = getattr(context, "repository", None)
    if repository is not None and loop is not None and callable(getattr(repository, "close", None)):
        loop.run_until_complete(repository.close())
    resource_names = (
        "adapter",
        "youcom_adapter",
        "tavily_keyless_adapter",
        "tavily_keyed_adapter",
        "tavily_cost_adapter",
        "tavily_stub_adapter",
        "tavily_held_adapter",
        "tavily_rest_adapter",
        "tavily_mcp_adapter",
        "tavily_fanout_adapter",
        "tavily_retry_adapter",
        "tavily_variant_adapter",
        "tavily_sched_adapter",
        "http_client",
        "brave_client",
        "exa_client",
        "firecrawl_client",
        "keenable_client",
        "parallel_client",
    )
    resources = [getattr(context, name, None) for name in resource_names]
    resources.extend(getattr(context, "tavily_caller_clients", []) or [])
    seen = set()
    for resource in resources:
        if resource is None or id(resource) in seen:
            continue
        seen.add(id(resource))
        if loop is not None and callable(getattr(resource, "aclose", None)):
            loop.run_until_complete(resource.aclose())
    patcher = getattr(context, "_execution_patcher", None)
    if patcher is not None:
        patcher.undo()
    # Directory cleanup and env restoration happen only after all DB users close.
    cleanups = getattr(context, "enc_cleanups", [])
    context.enc_cleanups = []
    for cleanup in cleanups:
        cleanup()
    if loop is not None:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
    database_path = getattr(context, "database_path", None)
    if database_path is not None:
        for test_path in (database_path, f"{database_path}.migration.lock"):
            _unlink_with_retries(test_path)
    temp_directory = getattr(context, "temp_directory", None)
    if temp_directory is not None:
        temp_directory.cleanup()


def _unlink_with_retries(path: str, *, attempts: int = 20) -> None:
    """Remove a test database after Windows releases delayed SQLite handles."""

    for attempt in range(attempts):
        try:
            os.unlink(path)
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            gc.collect()
            time.sleep(0.05)
        else:
            return


def _has_monitoring_tag(scenario: Any) -> bool:
    """Return True for offline monitoring scenarios, including feature-level tags.

    The monitoring tag sits on the feature (features/monitoring.feature), and
    Behave gives scenarios only their direct tags, so detection also reads the
    effective tag set. Real Behave scenarios expose ``effective_tags``; the
    fallback to ``tags`` + ``feature.tags`` keeps duck-typed doubles working.
    """

    effective_tags = getattr(scenario, "effective_tags", None)
    if effective_tags:
        return _tags_include_monitoring(effective_tags)
    tags = getattr(scenario, "tags", None) or ()
    feature_tags = getattr(getattr(scenario, "feature", None), "tags", None) or ()
    return _tags_include_monitoring((*tags, *feature_tags))


def _tags_include_monitoring(tags: Iterable[Any]) -> bool:
    """Return True when ``tags`` carries 'monitoring' (str or Tag forms)."""

    return any(str(getattr(tag, "name", tag)).lstrip("@") == "monitoring" for tag in tags)


def _has_control_tag(scenario: Any) -> bool:
    """Return True for offline control scenarios, including feature tags."""
    effective_tags = getattr(scenario, "effective_tags", None)
    if effective_tags:
        return _tags_include_control(effective_tags)
    tags = getattr(scenario, "tags", None) or ()
    feature_tags = getattr(getattr(scenario, "feature", None), "tags", None) or ()
    return _tags_include_control((*tags, *feature_tags))


def _tags_include_control(tags: Iterable[Any]) -> bool:
    """Return True when ``tags`` carries 'control' (str or Tag forms)."""

    return any(str(getattr(tag, "name", tag)).lstrip("@") == "control" for tag in tags)


def _has_fanout_tag(scenario: Any) -> bool:
    """Return True for offline fanout scenarios, including feature-level tags.

    Fanout scenarios run fully offline against stub adapters built in their
    own steps; they must never construct live provider adapters.
    """

    effective_tags = getattr(scenario, "effective_tags", None)
    if effective_tags:
        return _tags_include_fanout(effective_tags)
    tags = getattr(scenario, "tags", None) or ()
    feature_tags = getattr(getattr(scenario, "feature", None), "tags", None) or ()
    return _tags_include_fanout((*tags, *feature_tags))


def _has_limits_tag(scenario: Any) -> bool:
    """Return True for offline limit/CRD scenarios, including feature tags.

    Limit scenarios run fully offline against synthetic records and stub
    adapters built in their own steps; they must never construct live
    provider adapters.
    """

    effective_tags = getattr(scenario, "effective_tags", None)
    if effective_tags:
        return _tags_include_limits(effective_tags)
    tags = getattr(scenario, "tags", None) or ()
    feature_tags = getattr(getattr(scenario, "feature", None), "tags", None) or ()
    return _tags_include_limits((*tags, *feature_tags))


def _tags_include_limits(tags: Iterable[Any]) -> bool:
    """Return True when ``tags`` carries 'limits' or 's0' (str or Tag forms)."""

    names = {str(getattr(tag, "name", tag)).lstrip("@") for tag in tags}
    return "limits" in names or "s0" in names


def _tags_include_fanout(tags: Iterable[Any]) -> bool:
    """Return True when ``tags`` carries 'fanout' (str or Tag forms)."""

    return any(str(getattr(tag, "name", tag)).lstrip("@") == "fanout" for tag in tags)


def _has_users_tag(scenario: Any) -> bool:
    """Return True for offline users scenarios, including feature-level tags.

    The users tag sits on the feature (features/users.feature), and Behave
    gives scenarios only their direct tags, so detection also reads the
    effective tag set, mirroring the monitoring/control helpers.
    """

    effective_tags = getattr(scenario, "effective_tags", None)
    if effective_tags:
        return _tags_include_users(effective_tags)
    tags = getattr(scenario, "tags", None) or ()
    feature_tags = getattr(getattr(scenario, "feature", None), "tags", None) or ()
    return _tags_include_users((*tags, *feature_tags))


def _tags_include_users(tags: Iterable[Any]) -> bool:
    """Return True when ``tags`` carries 'users' (str or Tag forms)."""

    return any(str(getattr(tag, "name", tag)).lstrip("@") == "users" for tag in tags)


def _has_latency_tag(scenario: Any) -> bool:
    """Return True for routing-latency scenarios, including feature-level tags.

    The latency tag sits on the feature (features/routing_latency.feature and
    features/live/routing_latency_live.feature); detection reads the effective
    tag set, mirroring the monitoring/control helpers.
    """

    effective_tags = getattr(scenario, "effective_tags", None)
    if effective_tags:
        return _tags_include_latency(effective_tags)
    tags = getattr(scenario, "tags", None) or ()
    feature_tags = getattr(getattr(scenario, "feature", None), "tags", None) or ()
    return _tags_include_latency((*tags, *feature_tags))


def _tags_include_latency(tags: Iterable[Any]) -> bool:
    """Return True when ``tags`` carries 'latency' (str or Tag forms)."""

    return any(str(getattr(tag, "name", tag)).lstrip("@") == "latency" for tag in tags)


def _has_youcom_tag(scenario: Any) -> bool:
    """Return True when the scenario carries the 'youcom' tag (str or Tag forms)."""
    tags = getattr(scenario, "tags", None)
    if not tags:
        return False
    return any(str(getattr(tag, "name", tag)).lstrip("@") == "youcom" for tag in tags)


def _has_brave_tag(scenario: Any) -> bool:
    """Return True when the scenario carries the 'brave' tag (str or Tag forms)."""
    tags = getattr(scenario, "tags", None)
    if not tags:
        return False
    return any(getattr(tag, "name", tag) == "brave" for tag in tags)


def _has_keenable_tag(scenario: Any) -> bool:
    """Return True when the scenario carries the 'keenable' tag (str or Tag forms)."""
    tags = getattr(scenario, "tags", None)
    if not tags:
        return False
    return any(str(getattr(tag, "name", tag)).lstrip("@") == "keenable" for tag in tags)


def _has_keenable_keyed_tag(scenario: Any) -> bool:
    """Return True when the scenario carries the 'keenable-keyed' tag."""
    tags = getattr(scenario, "tags", None)
    if not tags:
        return False
    return any(str(getattr(tag, "name", tag)).lstrip("@") == "keenable-keyed" for tag in tags)


def _has_tinyfish_tag(scenario: Any) -> bool:
    """Identify offline Tinyfish scenarios, including feature-level tags."""
    tags = getattr(scenario, "tags", None) or ()
    feature_tags = getattr(getattr(scenario, "feature", None), "tags", None) or ()
    return any(
        str(getattr(tag, "name", tag)).lstrip("@") == "tinyfish" for tag in (*tags, *feature_tags)
    )


def _has_firecrawl_tag(scenario: Any) -> bool:
    """Return True when the scenario carries the bare 'firecrawl' tag (Behave form).

    Behave reports scenario tags as bare strings; a ``@firecrawl`` string is not
    a valid Behave tag form and deliberately does not select the adapter.
    """
    tags = getattr(scenario, "tags", None)
    if not tags:
        return False
    return any(getattr(tag, "name", tag) == "firecrawl" for tag in tags)


def _has_parallel_tag(scenario: Any) -> bool:
    """Return True when the scenario carries the bare 'parallel' tag (Behave form)."""
    tags = getattr(scenario, "tags", None)
    if not tags:
        return False
    return any(getattr(tag, "name", tag) == "parallel" for tag in tags)


def _has_quota_tag(scenario: Any) -> bool:
    """Return True for offline quota scenarios, including feature-level tags.

    The quota tag sits on the feature (features/quota.feature), and Behave
    gives scenarios only their direct tags, so detection also reads the
    effective tag set, mirroring the monitoring/control helpers.
    """

    effective_tags = getattr(scenario, "effective_tags", None)
    if effective_tags:
        return _tags_include_quota(effective_tags)
    tags = getattr(scenario, "tags", None) or ()
    feature_tags = getattr(getattr(scenario, "feature", None), "tags", None) or ()
    return _tags_include_quota((*tags, *feature_tags))


def _tags_include_quota(tags: Iterable[Any]) -> bool:
    """Return True when ``tags`` carries 'quota' (str or Tag forms)."""

    return any(str(getattr(tag, "name", tag)).lstrip("@") == "quota" for tag in tags)


def _has_live_tag(scenario: Any) -> bool:
    """Return True when the scenario carries the 'live' tag (str or Tag forms)."""

    tags = getattr(scenario, "tags", None) or ()
    feature_tags = getattr(getattr(scenario, "feature", None), "tags", None) or ()
    return any(
        str(getattr(tag, "name", tag)).lstrip("@") == "live" for tag in (*tags, *feature_tags)
    )
