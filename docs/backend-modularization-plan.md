# Backend modularization plan

**Status:** proposal only; no application or test files changed. Prepared from the current working tree on 11 September 2026.

Three subagents were assigned source layout, test layout, and runtime/configuration references. The source and reference reviews completed. The test reviewer reached a usage limit; the main agent completed the test mapping and used the newly installed CodeGraph to verify the important dependencies.

The inventory covers **128 tracked backend paths**: 36 source/package paths, 60 pytest/support/fixture paths (52 test modules), and 32 Behave paths (17 feature files, 14 step files, one environment hook). The proposed mapping moves 111 paths and leaves 17 in place. The already locally deleted `src/freesearch/py.typed` marker is counted as a tracked path, but this plan does not restore it.

## 1. Recommendation and scope

Retain the installable `src/freesearch` package and move whole modules into responsibility-based packages. Use separate `tests/unit` and `tests/integration` trees with directories mirroring source packages, plus `tests/bdd/features` for Behave. This gives the separate, mirrored test-source layout familiar from Java while retaining Python's `test_*.py` convention.

Preserve filenames, functions, classes, signatures, model fields, route registration, MCP tools, SQL, migrations, scenarios, assertions, fixture scopes and dependency versions. Do not split files, extract classes, rewrite tests, introduce abstractions, or “clean up” unrelated code.

**A scope detail:** a literal restriction to moves and import statements cannot safely accommodate all these moves. Console-entry-point strings, mock targets, fixture/root path expressions, Behave configuration, and Docker/Alembic paths must also follow the relocations. The recommendation includes only those mechanical path/reference adjustments and empty package markers; they are enumerated in section 7. No implementation or broader refactor has been performed. If even those mechanical adjustments are excluded, the affected files must stay in place.

Existing `freesearch` root contract reexports remain, with updated imports. CLI command names, REST paths, and MCP tool names remain stable. Old internal module paths such as `freesearch.contracts` change; no forwarding modules are proposed.

## 2. Target structure

```text
src/freesearch/
  __init__.py
  adapters/                       # Already a useful boundary; keep current files
    base.py
    brave.py, exa.py, firecrawl.py, keenable.py
    parallel.py, tavily.py, youcom.py, _youcom_support.py
  configuration/
    config.py
    provider_config.py
  models/
    contracts.py
  services/
    routing.py
    monitoring.py
    parallel_oauth.py
  infrastructure/
    http.py
    logging.py
    resilience.py
    secrets.py
  persistence/
    storage.py
    database_cli.py
    database_migrations.py
    migrations/
      env.py
      script.py.mako
      versions/                   # Preserve filenames and revision IDs
  routers/
    api.py
    control.py
  mcp/
    server.py
    surface.py

tests/
  conftest.py                      # Existing FakeAdapter and shared fixture stay together
  fixtures/parallel/               # Existing JSON fixtures stay here
  unit/                           # 36 existing pytest modules
    adapters/
    configuration/
    infrastructure/
    models/
    services/
    mcp/
    bdd/                          # Pytest tests of Behave hooks and steps
  integration/                    # 16 existing pytest modules
    routers/
    persistence/
    services/
    mcp/
    adversarial/                  # Existing OAuth security subtree, kept together
  bdd/
    features/
      environment.py
      *.feature
      steps/*.py                  # Preserve one flat shared step directory
```

Add empty `__init__.py` markers to the six new source packages: `configuration`, `models`, `services`, `infrastructure`, `persistence`, and `routers`. Keep existing package initializers and exports; do not add eager imports to the new markers.

For deterministic helper imports, also add empty markers to `tests`, `tests/unit` and its listed child directories, `tests/integration` and its listed child directories, `tests/bdd`, `tests/bdd/features`, and `tests/bdd/features/steps`. Preserve the existing adversarial marker. Fixture asset directories need no markers. Do not change pytest import mode or register new fixture plugins as part of this relocation.

## 3. Whole-file ownership and preserved limitations

| Destination | Ownership | What must remain mixed under this scope |
| --- | --- | --- |
| models/contracts.py | Provider-neutral contract DTOs, enums, validation | Contract helper functions remain in the same module. |
| configuration/config.py | Application settings and cached accessor | Settings models and accessor remain together. |
| configuration/provider_config.py | Provider configuration and registry | Configuration DTOs, registry and resolver accessors remain together. |
| services/routing.py | Provider eligibility, ordering and route selection | This is service routing, distinct from HTTP routers. |
| services/monitoring.py | Telemetry, quota and dashboard orchestration | Telemetry DTOs remain embedded in this service. |
| services/parallel_oauth.py | OAuth pairing, lifecycle, polling and balances | OAuth DTOs, HTTP client and workflow remain together. |
| infrastructure/* | HTTP setup, redaction/logging, resilience, secret storage | ProviderName remains in secrets.py; no extraction. |
| persistence/storage.py | SQLite repository and ORM | ORM row classes and aggregate models remain embedded here. |
| persistence/database_migrations.py | Migration adoption and upgrades | Result/status models remain here. |
| routers/api.py | REST application composition and endpoints | Dispatch helpers and application lifecycle remain here. |
| routers/control.py | Control-plane REST endpoints | Configuration, secret, breaker and quota service helpers remain here. |
| mcp/server.py | MCP server and composition | Shared adapter construction/lifecycle used by REST remains here. |
| adapters/* and mcp/surface.py | Existing provider and MCP boundaries | Preserve their current layout. |

This produces better module locations, not strictly independent architectural layers. In particular, `routers.api` and `routers.control` continue to import shared adapter helpers from `mcp.server`.

**Preserve the lazy import cycle:** CodeGraph verified `server.py:120` imports `control.effective_config_for_name` inside `_apply_parallel_seed`. Control imports `server.adapter_factory` at module scope. Update the lazy import to `freesearch.routers.control` but keep it inside that function. Hoisting it or introducing eager package reexports could create an import-time cycle.

Separating every embedded model, extracting services from control routes, and moving shared REST/MCP composition to a dedicated module would require a separate refactor and is excluded here.

## 4. Complete source/package mapping

All table paths are repository-relative. “Same” means no move; imports within unchanged files may still need updating. `py.typed` remains absent locally unless its owner restores it separately.

| Current path | Proposed path |
| --- | --- |
| `src/freesearch/__init__.py` | Same |
| `src/freesearch/adapters/__init__.py` | Same |
| `src/freesearch/adapters/_youcom_support.py` | Same |
| `src/freesearch/adapters/base.py` | Same |
| `src/freesearch/adapters/brave.py` | Same |
| `src/freesearch/adapters/exa.py` | Same |
| `src/freesearch/adapters/firecrawl.py` | Same |
| `src/freesearch/adapters/keenable.py` | Same |
| `src/freesearch/adapters/parallel.py` | Same |
| `src/freesearch/adapters/tavily.py` | Same |
| `src/freesearch/adapters/youcom.py` | Same |
| `src/freesearch/api.py` | `src/freesearch/routers/api.py` |
| `src/freesearch/config.py` | `src/freesearch/configuration/config.py` |
| `src/freesearch/contracts.py` | `src/freesearch/models/contracts.py` |
| `src/freesearch/control.py` | `src/freesearch/routers/control.py` |
| `src/freesearch/database_cli.py` | `src/freesearch/persistence/database_cli.py` |
| `src/freesearch/database_migrations.py` | `src/freesearch/persistence/database_migrations.py` |
| `src/freesearch/http.py` | `src/freesearch/infrastructure/http.py` |
| `src/freesearch/logging.py` | `src/freesearch/infrastructure/logging.py` |
| `src/freesearch/mcp/__init__.py` | Same |
| `src/freesearch/mcp/surface.py` | Same |
| `src/freesearch/migrations/__init__.py` | `src/freesearch/persistence/migrations/__init__.py` |
| `src/freesearch/migrations/env.py` | `src/freesearch/persistence/migrations/env.py` |
| `src/freesearch/migrations/script.py.mako` | `src/freesearch/persistence/migrations/script.py.mako` |
| `src/freesearch/migrations/versions/0001_legacy_baseline.py` | `src/freesearch/persistence/migrations/versions/0001_legacy_baseline.py` |
| `src/freesearch/migrations/versions/0002_canonical_quota_units.py` | `src/freesearch/persistence/migrations/versions/0002_canonical_quota_units.py` |
| `src/freesearch/migrations/versions/__init__.py` | `src/freesearch/persistence/migrations/versions/__init__.py` |
| `src/freesearch/monitoring.py` | `src/freesearch/services/monitoring.py` |
| `src/freesearch/parallel_oauth.py` | `src/freesearch/services/parallel_oauth.py` |
| `src/freesearch/provider_config.py` | `src/freesearch/configuration/provider_config.py` |
| `src/freesearch/py.typed` | Same |
| `src/freesearch/resilience.py` | `src/freesearch/infrastructure/resilience.py` |
| `src/freesearch/routing.py` | `src/freesearch/services/routing.py` |
| `src/freesearch/secrets.py` | `src/freesearch/infrastructure/secrets.py` |
| `src/freesearch/server.py` | `src/freesearch/mcp/server.py` |
| `src/freesearch/storage.py` | `src/freesearch/persistence/storage.py` |

## 5. Test classification and complete pytest mapping

Classify by what the file actually exercises, not by its docstring or whether HTTP is mocked:

- **Unit/component:** isolated contracts, configuration, routing, resilience, secret resolution, MCP surface, provider adapters with fake SDK/HTTP boundaries, and tests of the Behave harness.
- **Integration:** real SQLite/migrations, application transport composition, or workflows spanning routers, services, adapters and persistence. Offline integration tests still belong here.
- **Mixed files:** keep whole files intact and use integration when any substantial part exercises those integration boundaries.

Examples verified in source/CodeGraph: `test_parallel_oauth.py` creates real repositories and drives control endpoints; `test_runtime_settings.py` tests database-backed REST reads; `test_quota_units.py` tests adapter state hydration through persisted ledgers. They move intact into integration despite containing pure assertions too. `test_api.py` and `test_server.py` exercise real FastAPI/FastMCP composition with fake adapters.

The directory mirror is by package, not necessarily by filename: `tests/unit/adapters/test_brave_wire.py` belongs beside other tests of `src/freesearch/adapters/brave.py`. `test_foundation.py` spans settings, HTTP and logging; it stays whole under infrastructure. Adversarial security and BDD-harness tests are deliberate purpose-based exceptions to the source mirror.

| Current path | Proposed path |
| --- | --- |
| `tests/adversarial/THREAT_MODEL.md` | `tests/integration/adversarial/THREAT_MODEL.md` |
| `tests/adversarial/__init__.py` | `tests/integration/adversarial/__init__.py` |
| `tests/adversarial/conftest.py` | `tests/integration/adversarial/conftest.py` |
| `tests/adversarial/oauth_stubs.py` | `tests/integration/adversarial/oauth_stubs.py` |
| `tests/adversarial/test_adv_oauth_balance.py` | `tests/integration/adversarial/test_adv_oauth_balance.py` |
| `tests/adversarial/test_adv_oauth_contract.py` | `tests/integration/adversarial/test_adv_oauth_contract.py` |
| `tests/adversarial/test_adv_oauth_leakage.py` | `tests/integration/adversarial/test_adv_oauth_leakage.py` |
| `tests/adversarial/test_adv_oauth_lifecycle.py` | `tests/integration/adversarial/test_adv_oauth_lifecycle.py` |
| `tests/conftest.py` | Same |
| `tests/fixtures/parallel/extract.json` | Same |
| `tests/fixtures/parallel/search.json` | Same |
| `tests/providers/_youcom_test_support.py` | `tests/unit/adapters/_youcom_test_support.py` |
| `tests/providers/test_brave.py` | `tests/unit/adapters/test_brave.py` |
| `tests/providers/test_brave_edges.py` | `tests/unit/adapters/test_brave_edges.py` |
| `tests/providers/test_brave_resilience.py` | `tests/unit/adapters/test_brave_resilience.py` |
| `tests/providers/test_brave_wire.py` | `tests/unit/adapters/test_brave_wire.py` |
| `tests/providers/test_exa.py` | `tests/unit/adapters/test_exa.py` |
| `tests/providers/test_firecrawl.py` | `tests/unit/adapters/test_firecrawl.py` |
| `tests/providers/test_keenable.py` | `tests/unit/adapters/test_keenable.py` |
| `tests/providers/test_parallel.py` | `tests/unit/adapters/test_parallel.py` |
| `tests/providers/test_tavily.py` | `tests/unit/adapters/test_tavily.py` |
| `tests/providers/test_youcom_cost.py` | `tests/unit/adapters/test_youcom_cost.py` |
| `tests/providers/test_youcom_errors.py` | `tests/unit/adapters/test_youcom_errors.py` |
| `tests/providers/test_youcom_fetch.py` | `tests/unit/adapters/test_youcom_fetch.py` |
| `tests/providers/test_youcom_fetch_errors.py` | `tests/unit/adapters/test_youcom_fetch_errors.py` |
| `tests/providers/test_youcom_lifecycle.py` | `tests/unit/adapters/test_youcom_lifecycle.py` |
| `tests/providers/test_youcom_quota.py` | `tests/unit/adapters/test_youcom_quota.py` |
| `tests/providers/test_youcom_resilience.py` | `tests/unit/adapters/test_youcom_resilience.py` |
| `tests/providers/test_youcom_search.py` | `tests/unit/adapters/test_youcom_search.py` |
| `tests/providers/test_youcom_search_errors.py` | `tests/unit/adapters/test_youcom_search_errors.py` |
| `tests/test_adapter_contract.py` | `tests/unit/adapters/test_adapter_contract.py` |
| `tests/test_api.py` | `tests/integration/routers/test_api.py` |
| `tests/test_brave_bdd_environment.py` | `tests/unit/bdd/test_brave_bdd_environment.py` |
| `tests/test_brave_bdd_steps.py` | `tests/unit/bdd/test_brave_bdd_steps.py` |
| `tests/test_brave_bdd_steps_capabilities.py` | `tests/unit/bdd/test_brave_bdd_steps_capabilities.py` |
| `tests/test_contracts.py` | `tests/unit/models/test_contracts.py` |
| `tests/test_control_api.py` | `tests/integration/routers/test_control_api.py` |
| `tests/test_control_bdd_environment.py` | `tests/unit/bdd/test_control_bdd_environment.py` |
| `tests/test_database_migrations.py` | `tests/integration/persistence/test_database_migrations.py` |
| `tests/test_degenerate_quota.py` | `tests/integration/services/test_degenerate_quota.py` |
| `tests/test_exa_bdd_steps.py` | `tests/unit/bdd/test_exa_bdd_steps.py` |
| `tests/test_firecrawl_bdd_steps.py` | `tests/unit/bdd/test_firecrawl_bdd_steps.py` |
| `tests/test_foundation.py` | `tests/unit/infrastructure/test_foundation.py` |
| `tests/test_keenable_bdd_steps.py` | `tests/unit/bdd/test_keenable_bdd_steps.py` |
| `tests/test_manual_quota.py` | `tests/integration/routers/test_manual_quota.py` |
| `tests/test_mcp_surface.py` | `tests/unit/mcp/test_mcp_surface.py` |
| `tests/test_monitoring.py` | `tests/integration/services/test_monitoring.py` |
| `tests/test_monitoring_bdd_environment.py` | `tests/unit/bdd/test_monitoring_bdd_environment.py` |
| `tests/test_parallel_oauth.py` | `tests/integration/services/test_parallel_oauth.py` |
| `tests/test_provider_config.py` | `tests/unit/configuration/test_provider_config.py` |
| `tests/test_quota_units.py` | `tests/integration/services/test_quota_units.py` |
| `tests/test_resilience.py` | `tests/unit/infrastructure/test_resilience.py` |
| `tests/test_routing.py` | `tests/unit/services/test_routing.py` |
| `tests/test_runtime_settings.py` | `tests/integration/routers/test_runtime_settings.py` |
| `tests/test_secrets.py` | `tests/unit/infrastructure/test_secrets.py` |
| `tests/test_server.py` | `tests/integration/mcp/test_server.py` |
| `tests/test_storage.py` | `tests/integration/persistence/test_storage.py` |
| `tests/test_storage_aggregates.py` | `tests/integration/persistence/test_storage_aggregates.py` |
| `tests/test_tavily_bdd_steps.py` | `tests/unit/bdd/test_tavily_bdd_steps.py` |
| `tests/test_youcom_bdd_environment.py` | `tests/unit/bdd/test_youcom_bdd_environment.py` |

## 6. Complete Behave mapping

Move the entire current `features` tree to `tests/bdd/features`. Keep `environment.py`, all 17 feature files, and the flat `steps` directory together. Do not duplicate hooks, split step registries by provider, rename Gherkin steps, move scenarios between files, or alter tags. This preserves the existing shared lifecycle and step-registration behavior.

Pytest tests of these hooks/steps live separately in `tests/unit/bdd`; they are not BDD scenario execution.

| Current path | Proposed path |
| --- | --- |
| `features/adv_oauth_balance.feature` | `tests/bdd/features/adv_oauth_balance.feature` |
| `features/adv_oauth_device.feature` | `tests/bdd/features/adv_oauth_device.feature` |
| `features/adv_oauth_lifecycle.feature` | `tests/bdd/features/adv_oauth_lifecycle.feature` |
| `features/adv_oauth_security.feature` | `tests/bdd/features/adv_oauth_security.feature` |
| `features/brave.feature` | `tests/bdd/features/brave.feature` |
| `features/control.feature` | `tests/bdd/features/control.feature` |
| `features/database_migrations.feature` | `tests/bdd/features/database_migrations.feature` |
| `features/environment.py` | `tests/bdd/features/environment.py` |
| `features/exa.feature` | `tests/bdd/features/exa.feature` |
| `features/firecrawl.feature` | `tests/bdd/features/firecrawl.feature` |
| `features/keenable.feature` | `tests/bdd/features/keenable.feature` |
| `features/manual_quota.feature` | `tests/bdd/features/manual_quota.feature` |
| `features/monitoring.feature` | `tests/bdd/features/monitoring.feature` |
| `features/parallel.feature` | `tests/bdd/features/parallel.feature` |
| `features/parallel_oauth.feature` | `tests/bdd/features/parallel_oauth.feature` |
| `features/quota.feature` | `tests/bdd/features/quota.feature` |
| `features/steps/adv_oauth_steps.py` | `tests/bdd/features/steps/adv_oauth_steps.py` |
| `features/steps/brave_steps.py` | `tests/bdd/features/steps/brave_steps.py` |
| `features/steps/control_steps.py` | `tests/bdd/features/steps/control_steps.py` |
| `features/steps/database_migration_steps.py` | `tests/bdd/features/steps/database_migration_steps.py` |
| `features/steps/exa_steps.py` | `tests/bdd/features/steps/exa_steps.py` |
| `features/steps/firecrawl_steps.py` | `tests/bdd/features/steps/firecrawl_steps.py` |
| `features/steps/keenable_steps.py` | `tests/bdd/features/steps/keenable_steps.py` |
| `features/steps/manual_quota_steps.py` | `tests/bdd/features/steps/manual_quota_steps.py` |
| `features/steps/monitoring_steps.py` | `tests/bdd/features/steps/monitoring_steps.py` |
| `features/steps/parallel_oauth_steps.py` | `tests/bdd/features/steps/parallel_oauth_steps.py` |
| `features/steps/parallel_steps.py` | `tests/bdd/features/steps/parallel_steps.py` |
| `features/steps/quota_steps.py` | `tests/bdd/features/steps/quota_steps.py` |
| `features/steps/tavily_steps.py` | `tests/bdd/features/steps/tavily_steps.py` |
| `features/steps/youcom_steps.py` | `tests/bdd/features/steps/youcom_steps.py` |
| `features/tavily.feature` | `tests/bdd/features/tavily.feature` |
| `features/youcom.feature` | `tests/bdd/features/youcom.feature` |

## 7. Imports and mechanical reference changes

### 7.1 Python import migration

Use the source mapping as the authoritative module-prefix map, throughout source, pytest, Behave hooks/steps, and test support. Update module imports as well as symbol imports:

```python
# Before
from freesearch.contracts import SearchRequest
from freesearch import monitoring as monitoring_module
from freesearch.server import build_adapters

# After
from freesearch.models.contracts import SearchRequest
from freesearch.services import monitoring as monitoring_module
from freesearch.mcp.server import build_adapters
```

Keep aliases and imported module objects intact so existing monkeypatch seams still target the same lookup sites. Preserve lazy imports in their current scopes. Existing root `freesearch/__init__.py` reexports should import from `freesearch.models.contracts`; its `__all__` stays unchanged.

Update string mock targets too. For example, `test_monitoring.py` patches `freesearch.api.build_adapters` and `freesearch.server.build_adapters`; these become `freesearch.routers.api.build_adapters` and `freesearch.mcp.server.build_adapters`. Patch the consumer's lookup location, not merely the function's defining module.

Test/helper import mapping:

| Current reference | Replacement |
| --- | --- |
| `from conftest import FakeAdapter` | `from tests.conftest import FakeAdapter` |
| `from _youcom_test_support import ...` | `from tests.unit.adapters._youcom_test_support import ...` |
| `tests.adversarial.conftest` | `tests.integration.adversarial.conftest` |
| `tests.adversarial.oauth_stubs` | `tests.integration.adversarial.oauth_stubs` |
| `from features import environment` | `from tests.bdd.features import environment` |
| `from features.steps import ...` | `from tests.bdd.features.steps import ...` |

Keep `FakeAdapter` and its fixture in the existing root `tests/conftest.py`; extracting only the helper would violate the whole-file scope. Keep adversarial `conftest.py`, helpers, test modules, threat model and package initializer together. Behave's adversarial steps continue importing the same moved stub module.

The You.com support module exports pytest fixtures as well as helpers. Preserve the fixture imports in each consumer, including intentional unused-import annotations; do not auto-delete them or promote their autouse scope to the entire suite. Preserve test fixture names and all setup/teardown behavior.

### 7.2 Path-sensitive Python references

| File before relocation | Exact adjustment |
| --- | --- |
| All ten `tests/test_*_bdd_*.py` harness modules | Their new location is `tests/unit/bdd`; change repository-root calculations from `Path(__file__).resolve().parents[1]` to `parents[3]`. Keep the existing guarded sys.path insertion and update imports as above. |
| `tests/test_provider_config.py:32` | At `tests/unit/configuration/test_provider_config.py`, use `parents[3]` for the repository root; its `.env.example` check must still read the same file. |
| `tests/providers/test_parallel.py:55` | At `tests/unit/adapters/test_parallel.py`, fixtures remain `Path(__file__).resolve().parents[2] / "fixtures" / "parallel"`. |
| `tests/adversarial/test_adv_oauth_leakage.py:147` | Replace scan roots with `Path("tests/integration/adversarial")` and `Path("tests/bdd/features")`. Keep all scan patterns/exclusions unchanged. |
| `src/freesearch/database_migrations.py:114` | No expression change: moving this file and `migrations/` together preserves `Path(__file__).with_name("migrations")`. |

The leakage scan silently skips nonexistent roots, so a passing result with stale paths would not prove preserved coverage. As a migration check, verify both new roots exist and that the same non-marker files are included.

Leave runtime temporary-database/temp-directory paths alone: they describe test execution artifacts, not source locations. Leave database defaults, environment-variable names, keyring service names, provider IDs and endpoint paths unchanged.

### 7.3 Project configuration and tooling

| File/configuration | Required update |
| --- | --- |
| `pyproject.toml` → project.scripts | `freesearch-api = "freesearch.routers.api:main"`; `freesearch-db = "freesearch.persistence.database_cli:main"`; `freesearch-mcp = "freesearch.mcp.server:main"`. Command names stay the same. |
| `pyproject.toml` → tool.behave | Add `paths = ["tests/bdd/features"]` under `[tool.behave]` so an unqualified Behave run still discovers the suite. The installed Behave configuration loader supports this TOML table. |
| `pyproject.toml` → tool.ruff.src | Remove the old root `features` entry: use `["src", "tests"]`. |
| Ruff per-file ignores | Retarget the existing resilience exception to `src/freesearch/infrastructure/resilience.py`. Keep `"tests/**" = ["C901"]`; it now also covers BDD. Remove the obsolete `"features/**"` exception; no duplicate BDD exception is needed. |
| `alembic.ini:2` | `script_location = %(here)s/src/freesearch/persistence/migrations`. Keep `prepend_sys_path = %(here)s/src`. |
| `Dockerfile.test` | Remove `COPY features/ ./features/`; `COPY tests/ ./tests/` now includes BDD. Preserve other build/runtime settings. |
| Existing test commands and path filters | Retarget explicit filenames/subdirectories using the mapping. A broad `pytest tests` continues to run both pytest suites. |
| README, QUOTA, developer instructions | Update current module links, test paths and commands where they describe the current layout. |
| PROGRESS.md | Add a relocation note/map or correct current-use commands; retain historical records of old filenames as history rather than globally rewriting them. |
| Backend skill examples | Retarget old `features/` and moved `src/freesearch/*.py` examples in the backend BDD/code-quality skills if maintaining those repo-local instructions with the move. Do not change their policies. |

Keep these settings unchanged: Hatch `packages = ["src/freesearch"]`, pytest `testpaths = ["tests"]`, pytest strict/async settings, mypy `packages = ["freesearch"]` and `mypy_path = ["src"]`, dependency versions and the existing lockfile unless the package tool requires a metadata-only refresh.

The mutation wrapper `scripts/windows/run_gremlin_mutation_docker.bat` does not embed the old Python subdirectories. Its Dockerfile still targets `src/freesearch`, which remains correct. Do not silently change mutation-test selection or run a full mutation campaign as part of a relocation. Behave scenarios are not mutation-test targets.

No tracked CI workflow was found in this checkout. Update any subsequently added workflow/path filter that names a moved path. Frontend source and browser-test organization are outside this plan.

### 7.4 Import-path compatibility and observable metadata

Module relocation changes Python `__module__` identities and logger names derived from `logging.getLogger(__name__)` (monitoring, OAuth, migration runner). No forwarding shims, logger-name pins, or duplicate module registrations are proposed. Check known operational logging filters or external Python consumers for old module paths before rollout.

The application contracts should remain unchanged; verify OpenAPI and MCP schemas because schema generators can sometimes incorporate module identities. This plan does not claim that every piece of Python introspection metadata remains identical.

## 8. Implementation sequence

Use one structural change with reviewable commits; each commit must include the imports and runtime references required to remain runnable. Do not merge intermediate broken import states.

1. **Capture the working-tree baseline.** Record tracked paths, pytest node IDs (including parameter IDs), Behave scenario/step discovery, test outcomes, and current schemas. Separate existing failures from regressions. Preserve unrelated local changes, including the existing py.typed deletion, editor/CodeGraph setup and frontend work.
2. **Relocate source.** Create empty package markers, move the source files in section 4, update all consumers across source/tests/BDD, entry points, Ruff paths and Alembic configuration. Move the migration runner/history together. Keep adapters and existing MCP surface files in place.
3. **Relocate pytest files.** Move files using section 5, retaining shared root fixtures and fixture assets. Update helper imports, mock targets and repository/fixture path calculations in the same commit. Check fixture inheritance and each suite independently.
4. **Relocate Behave.** Move the whole features tree, update pytest harness imports and adversarial stub references, set tool.behave.paths, remove the obsolete Docker COPY, and fix the security scan roots. Validate shared step registration and hook execution together.
5. **Update current documentation and perform final verification.** Use the mapping to inspect remaining old references. Build and inspect the wheel, check offline tests and Docker build, review a rename-aware diff, and confirm no implementation/contract changes.

A source phase cannot update only src imports: tests, BDD and string targets are consumers and must change atomically. Likewise, a test move cannot be committed without its package/helper/path updates.

## 9. Verification and acceptance criteria

This planning task did not run the test suites or claim a green baseline. The following is the implementation validation plan.

### Structural checks

- Every existing backend path maps once, with no destination collision. Count remains 52 pytest modules and 17 feature files; new empty package markers are the only planned new Python files.
- Compare baseline and relocated pytest node IDs after applying the path mapping. Counts alone are insufficient: compare test names and parameter IDs too.
- Compare Behave features, scenarios/outline examples, step texts, tags, skip reasons and undefined/ambiguous steps. Renamed directories must not reduce discovery.
- Review `git diff --find-renames` and a path-aware source comparison. Apart from imports, enumerated reference/path changes and empty markers, function/class bodies, decorators, signatures, model fields, SQL and assertions must match.
- Keep both Alembic revision IDs, down_revision links and migration contents identical. Verify `script.py.mako` and revision files are included in the distribution.
- Check the remaining old-import/path references in code, configuration and current docs. Exclude this mapping and intentionally historical documentation from the “no stale reference” check.

### Routine commands after relocation

```powershell
uv run pytest --collect-only -q
uv run pytest tests/unit
uv run pytest tests/integration
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy
uv run python -m behave --dry-run
uv build
```

Run collection and relevant tests before relocation too, to establish a comparison. After both pytest partitions pass in isolation, run `uv run pytest` once to catch interactions between partitions and shared fixtures. Do not repeatedly broaden testing after these checks pass.

### Focused runtime checks

- Import the relocated public modules and factories from an installed wheel in a fresh environment, outside the checkout, with no editable install or source PYTHONPATH fallback. Check root contract reexports and all three console entry-point targets. This catches packaging failures that in-tree tests miss.
- Run the existing database migration tests and Behave migration scenarios. Smoke-test CLI upgrade/status against an explicit temporary database; `FREESEARCH_DB` takes precedence over `--database`, so isolate that environment value. Do not run these checks against the workspace database.
- Verify `migration_head()` from the installed wheel and Alembic script discovery through the updated INI configuration.
- Exercise REST and MCP lifecycle/contract tests: route registration, tool names/schemas, adapter creation/closure, quota hydration and telemetry behavior remain unchanged.
- Run all ten pytest BDD-harness modules. Check You.com fixture imports, root FakeAdapter imports, and adversarial fixture scope.
- Run the existing offline Behave files: control, monitoring, quota, manual_quota, parallel_oauth, database_migrations, and all four adv_oauth files. For example: `uv run python -m behave tests/bdd/features/control.feature tests/bdd/features/monitoring.feature tests/bdd/features/database_migrations.feature`. Execute the other listed offline files as well.
- Dry-run all provider features; keep their existing live-test gates and credential semantics. A relocation check does not require calls to paid/live providers.
- Build the updated Docker test image and run an ordinary pytest smoke/full suite in it to confirm the new COPY layout. A full mutation run is not required.
- Treat pre-existing py.typed absence and any baseline failures separately; do not restore or repair unrelated work to make the relocation appear clean.

## 10. CodeGraph evidence and use during implementation

The newly available index reported 235 indexed files, including 106 Python files, and an up-to-date state. CodeGraph was used for source and test exploration, not to modify or reindex the repository.

Relevant verified findings:

- `src/freesearch/server.py:113-138`: shared quota hydration uses the lazy control import discussed above.
- `src/freesearch/control.py:73`: endpoints are registered directly on FastAPI; do not replace that registration style.
- `tests/test_parallel_oauth.py:71` and `:995`: repository fixture plus real control-app composition justify integration placement.
- `tests/test_runtime_settings.py:37`: database-backed REST assertions justify integration placement.
- `tests/test_quota_units.py:1327`: adapter hydration goes through persisted repository state.
- `tests/adversarial/test_adv_oauth_leakage.py:146`: hardcoded scan roots can silently skip after relocation.
- `tests/providers/_youcom_test_support.py:245`: autouse fixture exports must retain their current consumer scope.
- `tests/test_brave_bdd_environment.py:31`: repository-root path arithmetic and direct Behave module imports require mechanical updates.
- `src/freesearch/database_cli.py:13`: FREESEARCH_DB precedence matters for isolated CLI validation.

Use `codegraph_explore` first when checking an affected symbol during implementation, then inspect literal path/config references as needed. Graph “affected tests” output is advisory: the default query in this mixed-language repo returned frontend results, while an explicit Python filter returned nested Python tests. It is not a substitute for the complete tracked-file manifest or pytest/Behave collection.

## 11. Done means

The backend is organized into the proposed packages; every existing test/support/feature file has its recorded home; ordinary pytest and Behave discovery still work; installed CLI and migrations resolve correctly; and the review shows only moves, import/reference/path updates, empty package markers and documentation changes. No source or test logic is split or rewritten.

