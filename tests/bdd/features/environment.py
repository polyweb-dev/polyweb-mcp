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
from freesearch.adapters.tinyfish import TinyfishAdapter
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
    context.has_tinyfish_key = _harness_env_key(ProviderName.TINYFISH) is not None


def before_scenario(context: Any, scenario: Any) -> None:
    """Set up async event loop, HTTP client, and provider adapter per scenario.

    Offline quota/monitoring/control scenarios win over provider tags: they
    return before any live gate or live adapter construction, so the offline
    path never constructs live adapters. Live provider quota scenarios
    (``@live @quota``) are exempted below so they fall through to live
    adapter construction and exercise the real vendor quota endpoints.
    A ``@live @keenable`` scenario runs
    only when ``FREESEARCH_RUN_LIVE=1``; otherwise it is skipped before any
    resource setup, keeping offline BDD runs network-safe (Keenable is
    keyless, so no key check can gate it).
    """
    if (
        _has_monitoring_tag(scenario)
        or _has_control_tag(scenario)
        or _has_fanout_tag(scenario)
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
    context.loop = asyncio.new_event_loop()
    asyncio.set_event_loop(context.loop)
    context.http_client = create_async_client()
    context.adapter = None
    context.youcom_adapter = None
    # Monitoring, control, and quota scenarios supply their own offline adapters and
    # repositories in their steps; never fall through to default provider
    # construction or a live network call.
    # You.com live scenarios skip before any adapter is constructed: TavilyAdapter
    # fails closed without a Tavily key, which would abort a You.com scenario
    # (e.g. when both provider keys are absent) instead of skipping it.
    if scenario is not None and any(tag == "youcom" for tag in scenario.tags):
        if not context.has_youcom_key:
            scenario.skip(
                reason=(
                    "FREESEARCH_YOU_API_KEY is not set "
                    "(harness live-gate reads the process env only). "
                    "You.com live BDD scenarios are skipped without a harness env key."
                )
            )
            return
        from freesearch.adapters.youcom import YoucomAdapter

        context.youcom_adapter = YoucomAdapter(
            context.http_client, api_key=_explicit_api_key(ProviderName.YOU)
        )
    else:
        if _has_brave_tag(scenario) and not getattr(context, "has_brave_key", True):
            scenario.skip(
                reason=(
                    "FREESEARCH_BRAVE_SEARCH_API_KEY is not set "
                    "(harness live-gate reads the process env only). "
                    "Brave live BDD scenarios are skipped without a harness env key."
                )
            )
            return
        if _has_parallel_tag(scenario) and not getattr(context, "has_parallel_key", True):
            scenario.skip(
                reason=(
                    "FREESEARCH_PARALLEL_API_KEY is not set "
                    "(harness live-gate reads the process env only). "
                    "Parallel live BDD scenarios are skipped without a harness env key."
                )
            )
            return
        if _has_keenable_keyed_tag(scenario) and not getattr(context, "has_keenable_key", True):
            scenario.skip(
                reason=(
                    "FREESEARCH_KEENABLE_API_KEY is not set "
                    "(harness live-gate reads the process env only). "
                    "Keenable keyed live BDD scenarios are skipped without a harness env key."
                )
            )
            return
        if _has_tinyfish_tag(scenario) and not getattr(context, "has_tinyfish_key", True):
            scenario.skip(
                reason=(
                    "FREESEARCH_TINYFISH_API_KEY is not set "
                    "(harness live-gate reads the process env only). "
                    "Tinyfish live BDD scenarios are skipped without a harness env key."
                )
            )
            return
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
    if _has_tinyfish_tag(scenario):
        return TinyfishAdapter(client, api_key=_explicit_api_key(ProviderName.TINYFISH))
    return TavilyAdapter(client, api_key=_explicit_api_key(ProviderName.TAVILY))


def _is_exa_scenario(scenario: Any) -> bool:
    """Identify scenarios declared by the Exa live feature."""
    return getattr(getattr(scenario, "feature", None), "name", "").startswith("Exa")


def after_scenario(context: Any, scenario: Any) -> None:
    """Clean up adapter resources, test repositories, and the async event loop."""
    cleanups = getattr(context, "enc_cleanups", [])
    context.enc_cleanups = []
    for cleanup in cleanups:
        with suppress(Exception):
            cleanup()
    repository = getattr(context, "repository", None)
    loop = getattr(context, "loop", None)
    if repository is not None and loop is not None and callable(getattr(repository, "close", None)):
        loop.run_until_complete(repository.close())
    adapter = getattr(context, "adapter", None)
    if adapter is not None and callable(getattr(adapter, "aclose", None)):
        context.loop.run_until_complete(adapter.aclose())
    youcom_adapter = getattr(context, "youcom_adapter", None)
    if youcom_adapter is not None and callable(getattr(youcom_adapter, "aclose", None)):
        context.loop.run_until_complete(youcom_adapter.aclose())
    if getattr(context, "http_client", None) is not None:
        context.loop.run_until_complete(context.http_client.aclose())
    if getattr(context, "loop", None) is not None:
        context.loop.close()
    database_path = getattr(context, "database_path", None)
    migration_lock_path = f"{database_path}.migration.lock" if database_path else None
    for test_path in (database_path, migration_lock_path):
        if test_path is not None:
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


def _tags_include_fanout(tags: Iterable[Any]) -> bool:
    """Return True when ``tags`` carries 'fanout' (str or Tag forms)."""

    return any(str(getattr(tag, "name", tag)).lstrip("@") == "fanout" for tag in tags)


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
    """Return True when the scenario carries the 'tinyfish' tag (str or Tag forms)."""
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
