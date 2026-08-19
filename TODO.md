# Stage 2: Routing Worktree

## Scope

Implement only the Routing responsibility from `WORKPLAN.md`: select providers
from caller preference, operation capability, local quota, health, and fallback
policy. This worktree uses the existing contracts and must not implement or
import individual providers.

Do not change `pyproject.toml`, `uv.lock`, shared contract models, application
composition, configuration, SQLite repositories, MCP, or resilience behavior.
Provider enablement and configured priority belong to the Configuration and
integration worktrees. Routing receives enabled adapters in configured priority
order.

## Developer Agent

### Deliverable

Add `src/freesearch/routing.py` with the smallest public API needed to produce
an ordered provider route for a `SearchRequest` or `FetchRequest`.

The route result must retain each selected adapter's `ProviderHealth` and
`QuotaSnapshot | None`. Do not expose a quota balance without the source label;
use the existing snapshot unchanged so `authoritative`, `observed`, and
`estimated` remain explicit.

Use a pure, synchronous selector. The caller supplies adapters, local health
snapshots, and local quota snapshots. The selector must not perform network,
database, configuration, or provider calls.

### Required Behavior

1. Determine the operation from the request type.
2. Exclude adapters that do not support that operation.
3. Exclude adapters with `HealthStatus.UNAVAILABLE`.
4. Exclude adapters whose known quota has `remaining == 0`.
5. Keep adapters with no quota snapshot or `remaining is None` eligible.
6. Rank eligible adapters by health: `HEALTHY`, then `DEGRADED`, then `UNKNOWN`.
7. Within a health group, apply `RoutingPreference` and then preserve supplied
   adapter order as the configured-priority tie breaker.
8. `AUTO` considers all eligible adapters in the ranking above.
9. `PREFER` moves recognized names in `preference.providers` ahead of other
   eligible adapters. Unknown names are ignored.
10. `REQUIRE` considers only names in `preference.providers`. If none are
    eligible, raise a provider-neutral structured routing error before an
    adapter is called. Unknown required names therefore fail this way.
11. When `allow_fallback` is false, return only the primary route. Otherwise,
    return the full ordered route for execution-time fallback.
12. Reject duplicate adapter names as invalid router input so selection is
    deterministic.

### Implementation Rules

- Reuse `ProviderAdapter` and the models in `freesearch.contracts`.
- Keep the implementation provider-neutral; do not import provider modules.
- Do not add dependencies or new shared Pydantic models.
- Keep adapter priority external: use the supplied adapter sequence order.
- Use a small provider-neutral routing exception for invalid/unsatisfied
  routing. Its error message must not include secrets or vendor response data.
- Prefer straightforward standard-library dataclasses and one selector over
  factories, registries, callbacks, or persistence abstractions.
- Do not update package re-exports unless a current import convention requires
  it; direct imports from `freesearch.routing` are sufficient.

## Tester Agent

### Deliverable

Add `tests/test_routing.py`. Own only test files; do not modify production
modules, contracts, dependencies, or the lockfile. Use small local
`ProviderAdapter` test doubles or extend the existing fake fixture only when it
reduces duplication without weakening existing tests.

### Required Coverage

1. Search and fetch capability filtering.
2. Exclusion of unavailable providers.
3. Exclusion of zero remaining quota and eligibility for absent/unknown quota.
4. Preservation of each quota snapshot's `QuotaSource`, including
   `ESTIMATED`, in route output.
5. Healthy-before-degraded-before-unknown ranking.
6. Stable configured-priority ordering when health and preference tie.
7. `AUTO`, `PREFER`, and `REQUIRE` behavior.
8. Ignored unknown preferred provider names and failed unknown required names.
9. A structured error when no required provider is eligible.
10. `allow_fallback=False` returning exactly one candidate and the default
    returning all ordered candidates.
11. Rejection of duplicate adapter names.

Use fixed UTC timestamps and explicit `Decimal` values. Tests must assert
observable route order and provenance rather than internal implementation
details.

## Quality Gates For Both Agents

- Respect ownership: routing depends only on existing contracts and adapter
  abstractions; no vendor, configuration, database, or HTTP imports.
- Keep the API typed and compatible with Python 3.11 and strict mypy.
- Preserve deterministic ordering and do not mutate supplied request, adapter,
  health, or quota objects.
- Never represent an `estimated` or `observed` quota as authoritative.
- Keep error messages provider-neutral and free of credentials or raw vendor
  payloads.
- Keep the diff limited to `src/freesearch/routing.py` and
  `tests/test_routing.py`, except for a necessary import-only package change.
- Run and pass:

```text
uv lock --check
uv sync --locked
uv run ruff check .
uv run mypy src
uv run pytest
```

## Completion Criteria

The developer implementation and tester coverage jointly demonstrate every
required behavior above. No fallback execution is implemented here: routing
only returns ordered candidates, and the future application layer executes
them. With fallback disabled, it returns only the primary candidate.
