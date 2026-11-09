"""Live-provider harness gates: missing-key scenarios skip before ANY setup.

Provider adapters take their key through the explicit constructor seam
(``api_key: SecretStr | None = None``); the retired
``get_provider_secret_resolver`` global is gone. ``before_scenario`` therefore
has to decide "can this live scenario run?" from the harness env alone
(``_harness_env_key``) and, when the key is absent, skip BEFORE it creates an
event loop, an HTTP client, or an adapter.

Tavily is the ``_adapter_for`` default and its live scenarios carry no provider
tag, so it is gated by ``_is_tavily_scenario`` (the exact complement of every
tag-driven selection). Firecrawl is gated by its own ``firecrawl`` tag. Both
gates once produced Behave hook errors in an offline run (TavilyAdapter /
FirecrawlAdapter fail closed without a key); these tests lock the skip-first
ordering, the construct-with-key path, and the no-key-leakage rule for the skip
reason. No live network call and no real credential is used anywhere here.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

from polyweb.infrastructure.secrets import PROVIDER_ENV_VARS, ProviderName

# ``features`` is an uninstalled namespace package at the repo root; make it
# importable regardless of pytest's sys.path manipulation.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from polyweb.adapters import youcom as youcom_module  # noqa: E402
from tests.bdd.features import environment  # noqa: E402

_TAVILY_REASON_KEY = "POLYWEB_TAVILY_API_KEY"
_FIRECRAWL_REASON_KEY = "POLYWEB_FIRECRAWL_API_KEY"


class _FakeClient:
    """Stand-in for the factory-created HTTP client."""

    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _FakeScenario:
    """Minimal behave Scenario stand-in recording tags and skip calls."""

    def __init__(
        self, tags: list[str], feature_name: str = "Tavily Provider Adapter Integration"
    ) -> None:
        self.tags = tags
        self.feature = SimpleNamespace(name=feature_name)
        self.skipped = False
        self.skip_reason: str | None = None

    def skip(self, reason: str | None = None) -> None:
        self.skipped = True
        self.skip_reason = reason

    def mark_skipped(self, reason: str | None = None) -> None:
        self.skip(reason)


class _RecordingAdapter:
    """Records every construction plus the explicit key it was handed."""

    instances: ClassVar[list["_RecordingAdapter"]] = []

    def __init__(self, client: object, api_key: object = None) -> None:
        self.client = client
        self.api_key = api_key
        self.closed = False
        type(self).instances.append(self)

    async def aclose(self) -> None:
        self.closed = True


class _ExplodingAdapter:
    """Construction raises: the scenario must have been skipped first."""

    def __init__(self, client: object, api_key: object = None) -> None:
        raise AssertionError("adapter must not be constructed for a keyless live scenario")


def _clear_harness_provider_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every harness provider key from the process env for this test."""
    for env_var in PROVIDER_ENV_VARS.values():
        monkeypatch.delenv(env_var, raising=False)


def _set_harness_key(monkeypatch: pytest.MonkeyPatch, provider: ProviderName, value: str) -> str:
    """Publish one fake harness key through the process env (the consumer seam)."""
    monkeypatch.setenv(PROVIDER_ENV_VARS[provider], value)
    return value


def _forbid_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every client factory and adapter constructor fail loudly if called."""

    def explode(*args: object, **kwargs: object) -> object:
        raise AssertionError("a skipped live scenario must not build any resource")

    monkeypatch.setattr(environment, "create_async_client", explode)
    for attribute in (
        "TavilyAdapter",
        "FirecrawlAdapter",
        "ParallelAdapter",
        "BraveAdapter",
        "KeenableAdapter",
        "ExaAdapter",
    ):
        monkeypatch.setattr(environment, attribute, _ExplodingAdapter, raising=False)
    monkeypatch.setattr(youcom_module, "YoucomAdapter", _ExplodingAdapter, raising=False)


def _tavily_scenario() -> _FakeScenario:
    """A live Tavily scenario: no provider tag, Tavily is the default adapter."""
    return _FakeScenario(["live", "search"])


def _firecrawl_scenario() -> _FakeScenario:
    """A live Firecrawl scenario: Behave reports the bare ``firecrawl`` tag."""
    return _FakeScenario(
        ["live", "firecrawl", "search"], feature_name="Firecrawl Provider Adapter Integration"
    )


# --- skip-first ordering (no key -> skipped before any setup) ------------------


def test_tavily_live_scenario_without_harness_key_skips_before_any_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No harness key: the Tavily live scenario is skipped before the event loop,
    the HTTP client, and any adapter construction (TavilyAdapter would otherwise
    fail closed and surface as a Behave hook error)."""
    _clear_harness_provider_keys(monkeypatch)
    _forbid_setup(monkeypatch)

    context = SimpleNamespace()
    environment.before_all(context)
    scenario = _tavily_scenario()

    environment.before_scenario(context, scenario)

    assert scenario.skipped is True
    assert _TAVILY_REASON_KEY in (scenario.skip_reason or "")
    assert not hasattr(context, "loop"), "skip must precede event-loop setup"
    assert not hasattr(context, "http_client"), "skip must precede client setup"
    assert not hasattr(context, "adapter"), "skip must precede adapter construction"

    # Teardown must stay safe when no loop/client was ever created.
    environment.after_scenario(context, scenario)


def test_firecrawl_live_scenario_without_harness_key_skips_before_any_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No harness key: the Firecrawl live scenario is skipped before the event
    loop, the HTTP client, and any adapter construction."""
    _clear_harness_provider_keys(monkeypatch)
    _forbid_setup(monkeypatch)

    context = SimpleNamespace()
    environment.before_all(context)
    scenario = _firecrawl_scenario()

    environment.before_scenario(context, scenario)

    assert scenario.skipped is True
    assert _FIRECRAWL_REASON_KEY in (scenario.skip_reason or "")
    assert not hasattr(context, "loop"), "skip must precede event-loop setup"
    assert not hasattr(context, "http_client"), "skip must precede client setup"
    assert not hasattr(context, "adapter"), "skip must precede adapter construction"

    environment.after_scenario(context, scenario)


def test_skip_reason_never_leaks_another_providers_key_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A skip reason names the missing env var and nothing else: key material for
    providers that ARE configured must never appear in it."""
    _clear_harness_provider_keys(monkeypatch)
    _forbid_setup(monkeypatch)
    secret = "super-secret-tavily-key-material"
    _set_harness_key(monkeypatch, ProviderName.TAVILY, secret)

    context = SimpleNamespace()
    environment.before_all(context)
    scenario = _firecrawl_scenario()

    environment.before_scenario(context, scenario)

    assert scenario.skipped is True
    reason = scenario.skip_reason or ""
    assert _FIRECRAWL_REASON_KEY in reason
    assert secret not in reason, "skip reason leaked another provider's key material"
    assert PROVIDER_ENV_VARS[ProviderName.TAVILY] not in reason, (
        "the reason must name only the missing key"
    )


# --- construct-with-key path --------------------------------------------------


def test_tavily_live_scenario_with_harness_key_constructs_adapter_with_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the harness key present the Tavily default adapter is constructed on
    the factory client with that key on the explicit ``api_key`` seam."""
    _clear_harness_provider_keys(monkeypatch)
    key = _set_harness_key(monkeypatch, ProviderName.TAVILY, "harness-tavily-key")
    _RecordingAdapter.instances.clear()
    fake_client = _FakeClient()
    monkeypatch.setattr(environment, "create_async_client", lambda: fake_client)
    monkeypatch.setattr(environment, "TavilyAdapter", _RecordingAdapter)

    context = SimpleNamespace()
    environment.before_all(context)
    scenario = _tavily_scenario()
    try:
        environment.before_scenario(context, scenario)
        assert scenario.skipped is False
        assert isinstance(context.adapter, _RecordingAdapter)
        assert context.adapter.client is fake_client, "adapter must own the factory client"
        assert _RecordingAdapter.instances == [context.adapter]
        assert context.adapter.api_key is not None, "the harness key must reach the seam"
        assert context.adapter.api_key.get_secret_value() == key
    finally:
        environment.after_scenario(context, scenario)

    assert context.adapter.closed is True
    assert context.http_client.closed is True


def test_firecrawl_live_scenario_with_harness_key_constructs_adapter_with_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the harness key present the tag-selected Firecrawl adapter is built on
    the factory client with that key on the explicit ``api_key`` seam."""
    _clear_harness_provider_keys(monkeypatch)
    key = _set_harness_key(monkeypatch, ProviderName.FIRECRAWL, "harness-firecrawl-key")
    _RecordingAdapter.instances.clear()
    fake_client = _FakeClient()
    monkeypatch.setattr(environment, "create_async_client", lambda: fake_client)
    monkeypatch.setattr(environment, "TavilyAdapter", _ExplodingAdapter)
    monkeypatch.setattr(environment, "FirecrawlAdapter", _RecordingAdapter)

    context = SimpleNamespace()
    environment.before_all(context)
    scenario = _firecrawl_scenario()
    try:
        environment.before_scenario(context, scenario)
        assert scenario.skipped is False
        assert isinstance(context.adapter, _RecordingAdapter)
        assert context.adapter.client is fake_client, "adapter must own the factory client"
        assert context.adapter.api_key is not None, "the harness key must reach the seam"
        assert context.adapter.api_key.get_secret_value() == key
    finally:
        environment.after_scenario(context, scenario)

    assert context.adapter.closed is True
    assert context.http_client.closed is True


# --- ``_is_tavily_scenario`` truth table --------------------------------------


def test_is_tavily_scenario_true_exactly_for_the_live_adapter_for_default() -> None:
    """``_is_tavily_scenario`` must be True for the live scenarios that fall
    through to the Tavily default (tavily.feature carries only ``@live``).

    The predicate is live-scoped: an untagged NON-live scenario is never
    key-gated, so ordinary offline steps keep their default adapter.
    """
    assert environment._is_tavily_scenario(_tavily_scenario()) is True
    assert environment._is_tavily_scenario(_FakeScenario(["live", "search"])) is True
    assert (
        environment._is_tavily_scenario(
            _FakeScenario(["live", "quota"], feature_name="Tavily Provider Adapter Integration")
        )
        is True
    )
    assert environment._is_tavily_scenario(_FakeScenario(["search"])) is False
    assert environment._is_tavily_scenario(SimpleNamespace(tags=[])) is False


def test_is_tavily_scenario_false_for_every_other_provider_selection() -> None:
    """Every tag-driven selection - and the separately gated ``@youcom`` path -
    must exclude the Tavily gate, so no scenario is gated twice."""
    context = SimpleNamespace(
        has_youcom_key=False,
        has_parallel_key=False,
        has_firecrawl_key=False,
        has_keenable_key=False,
        has_brave_key=False,
        has_tavily_key=False,
        has_tinyfish_key=False,
    )
    other_scenarios = (
        _firecrawl_scenario(),
        _FakeScenario(["live", "parallel", "search"]),
        _FakeScenario(["live", "brave", "search"]),
        _FakeScenario(["live", "keenable", "keenable-keyed", "search"]),
        _FakeScenario(["live", "tinyfish-live", "search"]),
        _FakeScenario(["youcom", "live", "search"]),
    )

    for scenario in other_scenarios:
        assert environment._is_tavily_scenario(scenario) is False, scenario.tags
        reason = environment._missing_live_key_reason(context, scenario)
        assert reason is not None, scenario.tags
        assert _TAVILY_REASON_KEY not in reason, (
            f"{scenario.tags} must be gated on its own provider key, not Tavily's"
        )

    # Plain (keyless) Keenable is gated on POLYWEB_RUN_LIVE, not on a key, and
    # Exa is identified by feature name: neither may reach the Tavily gate.
    for scenario in (
        _FakeScenario(["live", "keenable", "search"]),
        _FakeScenario(["live", "search"], feature_name="Exa Provider Adapter Integration"),
    ):
        assert environment._is_tavily_scenario(scenario) is False, scenario.tags
        assert environment._missing_live_key_reason(context, scenario) is None, scenario.tags


def test_harness_env_key_prefers_canonical_and_accepts_legacy_tinyfish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tinyfish reads POLYWEB_TINYFISH_API_KEY first, then the legacy spelling."""
    monkeypatch.delenv("POLYWEB_TINYFISH_API_KEY", raising=False)
    monkeypatch.setenv("TINYFISH_API_KEY", "legacy-fixture")
    assert environment._harness_env_key(ProviderName.TINYFISH) == "legacy-fixture"
    monkeypatch.setenv("POLYWEB_TINYFISH_API_KEY", "canonical-fixture")
    assert environment._harness_env_key(ProviderName.TINYFISH) == "canonical-fixture"


def test_harness_env_key_treats_blank_as_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """A dotenv line such as ``KEY=`` must not count as a configured key."""
    monkeypatch.setenv(PROVIDER_ENV_VARS[ProviderName.KEENABLE], "  ")
    assert environment._harness_env_key(ProviderName.KEENABLE) is None


def test_keyless_keenable_ignores_a_configured_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keyless scenarios run on the public tier even when a Keenable key is set."""
    from polyweb.models.provider_limits import AuthMode

    monkeypatch.setenv(PROVIDER_ENV_VARS[ProviderName.KEENABLE], "keenable-fixture")
    keyless = environment._adapter_for(_FakeClient(), _FakeScenario(["live", "keenable"]))
    keyed = environment._adapter_for(
        _FakeClient(), _FakeScenario(["live", "keenable", "keenable-keyed"])
    )
    assert keyless.limit_auth_mode is AuthMode.KEYLESS
    assert keyed.limit_auth_mode is AuthMode.KEYED


def test_live_tinyfish_scenario_builds_tinyfish_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    """The live Tinyfish feature gets a Tinyfish adapter built from the harness key."""
    monkeypatch.setenv("POLYWEB_TINYFISH_API_KEY", "tinyfish-fixture")
    adapter = environment._adapter_for(_FakeClient(), _FakeScenario(["live", "tinyfish-live"]))
    assert adapter.name == "tinyfish"
