"""Tests for the provider configuration registry.

Coverage maps to the stage contract (AC-1..AC-6) and the stage-2 remediation
review findings: partial estimate merges, strict typed fields, registry
isolation from caller mutation, secret input redaction in validation errors,
and ``.env``/cache isolation. Credentials live only in the encrypted vault;
this module pins that no secret seam exists here.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from freesearch.configuration.config import get_settings
from freesearch.configuration.provider_config import (
    ProviderConfig,
    ProviderConfigSettings,
    ProviderConfigUpdate,
    get_provider_configs,
)
from freesearch.infrastructure.secrets import ProviderName
from freesearch.models.contracts import QuotaSource, UsageOperation

OVERRIDES_ENV = "FREESEARCH_PROVIDER_CONFIG_OVERRIDES"

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch, tmp_path) -> None:
    """Isolate every test from ambient settings, cwd, and cache state.

    A developer's ``.env`` or an exported ``FREESEARCH_PROVIDER_CONFIG_OVERRIDES``
    must not change tests that expect defaults, so each test runs in a fresh
    directory with the override variable unset. All process-wide accessors are
    cleared before and after so sibling state cannot leak in.
    """

    monkeypatch.delenv(OVERRIDES_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    get_provider_configs.cache_clear()
    yield
    get_settings.cache_clear()
    get_provider_configs.cache_clear()


# AC-1: defaults for every provider, strict unknown-field rejection.


def test_default_registry_covers_every_provider() -> None:
    registry = get_provider_configs()

    assert set(registry) == set(ProviderName)
    for record in registry.values():
        assert record.enabled is True
        assert record.priority > 0
        assert set(record.free_tier_estimates) == set(UsageOperation)
        for units in record.free_tier_estimates.values():
            assert isinstance(units, Decimal)
            assert units >= 0
        assert record.reset_schedule is None


def test_provider_config_rejects_unknown_record_fields() -> None:
    with pytest.raises(ValidationError):
        ProviderConfig(api_key="secret")


# AC-2: single JSON override setting through the environment flow.


def test_override_json_is_read_from_environment(monkeypatch) -> None:
    monkeypatch.setenv(OVERRIDES_ENV, '{"exa": {"priority": 10, "reset_schedule": "monthly"}}')

    overrides = ProviderConfigSettings().provider_config_overrides

    assert set(overrides) == {ProviderName.EXA}
    update = overrides[ProviderName.EXA]
    assert update.priority == 10
    assert update.reset_schedule == "monthly"


def test_override_merges_over_defaults(monkeypatch) -> None:
    monkeypatch.setenv(
        OVERRIDES_ENV,
        '{"exa": {"priority": 10, "reset_schedule": "monthly"}, "tavily": {"enabled": false}}',
    )

    registry = get_provider_configs()

    exa = registry[ProviderName.EXA]
    assert exa.priority == 10
    assert exa.reset_schedule == "monthly"
    assert exa.enabled is True  # unset fields keep defaults
    assert registry[ProviderName.TAVILY].enabled is False
    untouched = registry[ProviderName.FIRECRAWL]
    assert untouched.priority == 100
    assert untouched.enabled is True


def test_partial_free_tier_estimates_override_preserves_other_operations(monkeypatch) -> None:
    monkeypatch.setenv(OVERRIDES_ENV, '{"exa": {"free_tier_estimates": {"search": 1}}}')

    exa = get_provider_configs()[ProviderName.EXA]

    assert exa.free_tier_estimates[UsageOperation.SEARCH] == Decimal("1")
    assert exa.free_tier_estimates[UsageOperation.FETCH] == Decimal("0")
    assert exa.free_tier_estimates[UsageOperation.COST_ESTIMATE] == Decimal("0")
    assert exa.priority == 100


def test_apply_to_merges_partial_estimates_onto_base() -> None:
    base = ProviderConfig(
        free_tier_estimates={
            UsageOperation.SEARCH: Decimal("5"),
            UsageOperation.FETCH: Decimal("2"),
            UsageOperation.COST_ESTIMATE: Decimal("0"),
        }
    )
    merged = ProviderConfigUpdate(
        free_tier_estimates={UsageOperation.FETCH: Decimal("7")}
    ).apply_to(base)

    assert merged.free_tier_estimates[UsageOperation.SEARCH] == Decimal("5")
    assert merged.free_tier_estimates[UsageOperation.FETCH] == Decimal("7")
    assert merged.free_tier_estimates[UsageOperation.COST_ESTIMATE] == Decimal("0")


def test_default_registry_usable_without_override(monkeypatch) -> None:
    monkeypatch.delenv(OVERRIDES_ENV, raising=False)

    assert ProviderConfigSettings().provider_config_overrides == {}
    registry = get_provider_configs()
    assert all(record.enabled and record.priority == 100 for record in registry.values())


@pytest.mark.parametrize(
    "raw",
    [
        "{not valid json",
        "",
        '{"nope": {"priority": 1}}',
        '{"exa": {"priority": 1, "api_key": "x"}}',
        '{"exa": {"priority": 0}}',
        '{"exa": {"priority": -3}}',
        '{"exa": {"free_tier_estimates": {"search": -1}}}',
        '{"exa": {"enabled": "yes"}}',
        '{"exa": {"priority": "10"}}',
        '{"exa": {"free_tier_estimates": {"search": 0.5}}}',
    ],
)
def test_invalid_override_raises_validation_error(monkeypatch, raw: str) -> None:
    monkeypatch.setenv(OVERRIDES_ENV, raw)

    with pytest.raises(ValidationError):
        ProviderConfigSettings()


def test_negative_estimate_rejected_directly() -> None:
    with pytest.raises(ValidationError):
        ProviderConfig(free_tier_estimates={UsageOperation.SEARCH: Decimal("-0.5")})


@pytest.mark.parametrize(
    "payload",
    [
        {"enabled": "yes"},
        {"enabled": 1},
        {"priority": "10"},
        {"priority": 10.0},
        {"free_tier_estimates": {"search": 0.5}},
    ],
)
def test_strict_typed_fields_reject_coercible_input(payload: dict) -> None:
    """String/integer coercion is no longer accepted for bool/int/Decimal fields."""

    for model in (ProviderConfig, ProviderConfigUpdate):
        with pytest.raises(ValidationError):
            model(**payload)


# AC-3: reset schedule opaque/non-empty; provenance always ESTIMATED.


def test_reset_schedule_must_be_non_empty() -> None:
    assert ProviderConfig(reset_schedule="monthly").reset_schedule == "monthly"
    with pytest.raises(ValidationError):
        ProviderConfig(reset_schedule="")
    with pytest.raises(ValidationError):
        ProviderConfig(reset_schedule="   ")


def test_quota_source_is_estimated_and_not_configurable() -> None:
    assert get_provider_configs()[ProviderName.EXA].quota_source == QuotaSource.ESTIMATED
    with pytest.raises(ValidationError):
        ProviderConfig(quota_source=QuotaSource.AUTHORITATIVE)


# AC-4: no secret fields on records and no resolver seam; validation errors
# never echo secret input.


def test_configuration_records_contain_no_secret_fields() -> None:
    registry = get_provider_configs()
    for record in registry.values():
        for name in type(record).model_fields:
            assert "key" not in name.lower() and "secret" not in name.lower()
        dumped = record.model_dump()
        assert "api_key" not in dumped and "secret" not in dumped


def test_provider_config_has_no_resolver_seam() -> None:
    """Vault-only: adapters receive injected vault keys; no resolver lives here."""

    import freesearch.configuration.provider_config as provider_config_module

    assert not hasattr(provider_config_module, "get_provider_secret_resolver")


@pytest.mark.parametrize(
    "payload",
    [
        {"api_key": "sk-super-secret-abc"},
        {"enabled": "secret-token-123"},
        {"priority": "secret-token-123"},
    ],
)
def test_validation_errors_do_not_expose_supplied_input(payload: dict) -> None:
    """Logged ValidationError text must not echo the failing input value."""

    for model in (ProviderConfig, ProviderConfigUpdate):
        with pytest.raises(ValidationError) as excinfo:
            model(**payload)
        message = str(excinfo.value)
        assert all(str(value) not in message for value in payload.values())


def test_env_override_validation_error_hides_secret_input(monkeypatch) -> None:
    monkeypatch.setenv(OVERRIDES_ENV, '{"exa": {"api_key": "sk-super-secret-abc"}}')

    with pytest.raises(ValidationError) as excinfo:
        ProviderConfigSettings()
    assert "sk-super-secret-abc" not in str(excinfo.value)


# AC-5: cached runtime accessor is isolated by cache clearing, and caller
# mutations never leak into later reads.


def test_get_provider_configs_is_cached(monkeypatch) -> None:
    monkeypatch.setenv(OVERRIDES_ENV, '{"exa": {"priority": 7}}')

    first = get_provider_configs()
    assert first[ProviderName.EXA].priority == 7

    monkeypatch.delenv(OVERRIDES_ENV, raising=False)
    still_cached = get_provider_configs()
    assert still_cached[ProviderName.EXA].priority == 7  # env change ignored while cached
    assert still_cached is not first  # each read is a fresh mapping copy

    get_provider_configs.cache_clear()
    assert get_provider_configs()[ProviderName.EXA].priority == 100


def test_returned_mapping_is_isolated_from_caller_mapping_mutation() -> None:
    first = get_provider_configs()
    first[ProviderName.EXA] = first[ProviderName.YOU]
    first.pop(ProviderName.BRAVE)
    first.clear()

    later = get_provider_configs()

    assert set(later) == set(ProviderName)
    assert later[ProviderName.EXA] is not later[ProviderName.YOU]


def test_returned_records_are_isolated_from_caller_record_mutation() -> None:
    first = get_provider_configs()
    with pytest.raises(ValidationError):
        first[ProviderName.EXA].enabled = False  # frozen record
    first[ProviderName.EXA].free_tier_estimates[UsageOperation.SEARCH] = Decimal("999")

    later = get_provider_configs()

    assert later[ProviderName.EXA].enabled is True
    assert later[ProviderName.EXA].free_tier_estimates[UsageOperation.SEARCH] == Decimal("0")


def test_override_applies_to_partial_update_record() -> None:
    update = ProviderConfigUpdate(priority=5)
    merged = update.apply_to(ProviderConfig())

    assert merged.priority == 5
    assert merged.enabled is True
    assert merged.reset_schedule is None


def test_env_file_override_and_environment_precedence(monkeypatch, tmp_path) -> None:
    """A cwd ``.env`` is honored, and a real environment variable wins over it.

    The autouse fixture has already chdir'd to ``tmp_path``, so the ``.env``
    written below is the one the settings layer reads.
    """

    (tmp_path / ".env").write_text(
        f"{OVERRIDES_ENV}={json.dumps({'exa': {'priority': 3}})}",
        encoding="utf-8",
    )
    get_provider_configs.cache_clear()
    assert get_provider_configs()[ProviderName.EXA].priority == 3

    monkeypatch.setenv(OVERRIDES_ENV, json.dumps({"exa": {"priority": 4}}))
    get_provider_configs.cache_clear()
    assert get_provider_configs()[ProviderName.EXA].priority == 4


# AC-6: .env.example documents a valid non-secret JSON override example.


def test_env_example_documents_valid_json_override(monkeypatch) -> None:
    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    line = next(line for line in env_example.splitlines() if f"{OVERRIDES_ENV}=" in line)

    parsed = json.loads(line.split("=", 1)[1].strip())
    assert isinstance(parsed, dict)
    assert set(parsed) <= {provider.value for provider in ProviderName}

    # The documented payload must be schema-valid end to end.
    monkeypatch.setenv(OVERRIDES_ENV, json.dumps(parsed))
    get_provider_configs.cache_clear()
    registry = get_provider_configs()
    assert set(registry) == set(ProviderName)
    assert registry[ProviderName.EXA].priority == 10
    assert registry[ProviderName.TAVILY].enabled is False
