"""Preset fault scenarios.

The package ships JSON presets in ``polyweb_provider_mock/scenarios/``:
``{"description": str, "faults": [FaultSpec, ...]}``. Every provider plugin
also gets a generated ``<provider>-down`` preset. Applying a preset adds its
rules tagged with the preset name, so ``scenario clear`` removes exactly
those rules.
"""

import json
from collections.abc import Iterable
from importlib import resources

from pydantic import BaseModel, ConfigDict

from polyweb_provider_mock.faults import FaultKind, FaultParams, FaultRule, FaultSpec
from polyweb_provider_mock.store import MockStore

__all__ = ["Scenario", "apply_scenario", "clear_scenarios", "scenarios"]


class Scenario(BaseModel):
    """A named set of fault rules."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    faults: tuple[FaultSpec, ...]


def _shipped() -> list[Scenario]:
    folder = resources.files("polyweb_provider_mock").joinpath("scenarios")
    found: list[Scenario] = []
    for item in sorted(folder.iterdir(), key=lambda entry: entry.name):
        if item.name.endswith(".json"):
            data = json.loads(item.read_text(encoding="utf-8"))
            found.append(Scenario(name=item.name.removesuffix(".json"), **data))
    return found


def scenarios(providers: Iterable[str]) -> dict[str, Scenario]:
    """Return every preset by name, including ``<provider>-down`` for each provider."""

    presets = {scenario.name: scenario for scenario in _shipped()}
    for provider in sorted(providers):
        name = f"{provider}-down"
        presets[name] = Scenario(
            name=name,
            description=f"Every {provider} operation answers 503 in {provider}'s format.",
            faults=(
                FaultSpec(provider=provider, kind=FaultKind.OUTAGE, params=FaultParams(status=503)),
            ),
        )
    return presets


def apply_scenario(store: MockStore, name: str, providers: Iterable[str]) -> list[FaultRule]:
    """Replace the rules of preset ``name`` with a fresh copy; return the new rules."""

    presets = scenarios(providers)
    if name not in presets:
        raise KeyError(f"unknown scenario {name!r}; known: {', '.join(sorted(presets))}")
    store.clear_faults(scenario=name)
    return [
        store.add_fault(spec.model_copy(update={"scenario": name})) for spec in presets[name].faults
    ]


def clear_scenarios(store: MockStore, providers: Iterable[str], name: str | None = None) -> int:
    """Remove the rules of one preset, or of every preset when ``name`` is ``None``."""

    names = [name] if name is not None else list(scenarios(providers))
    return sum(store.clear_faults(scenario=item) for item in names)
