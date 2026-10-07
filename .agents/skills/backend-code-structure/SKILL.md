---
name: backend-code-structure
description: "Guidelines and conventions for backend module boundaries, package responsibilities, import hygiene, and mirrored unit/integration/BDD test layouts. Use when creating new modules, refactoring backend code, structuring tests, or auditing package boundaries."
---

# Backend Code Structure & Architecture Guidelines

A clean, modular architecture enforcing single responsibility per package, unidirectional dependencies, clean import boundaries, and a mirrored test layout.

---

## 1. Package Responsibilities (`src/<app>/`)

Modules are strictly organized by operational role and dependency layering:

| Package | Purpose & Ownership | Constraints & Rules |
| :--- | :--- | :--- |
| **`models/`** | Domain contracts, DTOs, schemas, enums, validation. | Pure data structures. Use Pydantic explicitly for each contract. Do not import transport, database, or vendor SDK modules. |
| **`configuration/`** | Settings models, environment variable loaders, provider configs, registries. | Exposes cached/singleton accessors. No operational business logic. |
| **`services/`** | Core business logic, routing, monitoring, orchestration, and domain workflows. | Distinct from HTTP routers. Depends on models, persistence, and adapters via interfaces. |
| **`adapters/`** | External third-party integrations implementing unified interfaces. | Encapsulates vendor-specific HTTP/SDK calls and error mapping into domain contracts. |
| **`infrastructure/`** | Cross-cutting technical plumbing (HTTP clients, logging, resilience/circuit breakers, secrets/keyring). | Reusable technical utilities; independent of domain business rules. |
| **`persistence/`** | Storage repositories, database ORM/tables, migration runners, and Alembic version scripts. | Owns schema definitions and raw queries. Returns domain models or entity aggregates. |
| **`routers/`** | Transport-layer endpoints (REST API, control plane). | Thin handlers: validate request parameters, call services, and return responses. No inline DB queries. |
| **`mcp/`** | MCP server composition, surface schemas, tool registrations, and lifecycle execution. | Exposes capabilities via the Model Context Protocol; delegates work to services/adapters. |

The codebase uses Pydantic actively. `models/contracts.py` and `models/observability.py` define the domain contracts as Pydantic models. Each new domain contract must use Pydantic explicitly.

---

## 2. Dependency Flow & Import Hygiene

### Unidirectional Dependency Flow

```
[ routers/ & mcp/ ] (Transport Layer)
        │
        ▼
   [ services/ ] (Domain Logic & Orchestration)
   ┌────┼──────────────┐
   ▼    ▼              ▼
[ adapters/ ]  [ persistence/ ]  [ infrastructure/ ]
   │    │              │                │
   └────┴───────┬──────┴────────────────┘
                ▼
      [ models/ & configuration/ ] (Foundations)
```

1. **Strict Layering**: Upper layers may import from lower layers; lower layers must never import from upper layers. Never import from `routers/` or `mcp/` inside `services/` or `persistence/`.
2. **Package Import Paths**: Use explicit, absolute package imports (e.g., `from freesearch.models.contracts import SearchRequest`). Avoid relative imports spanning across package boundaries (`../../`).
3. **Clean `__init__.py` Markers**: Keep package initializers lean. Avoid eager cascading imports that cause circular dependency chains.
4. **Circular Dependency Handling**:
   - Prefer extracting shared contracts to `models/` or using dependency injection.
   - If runtime composition demands a mutual reference (e.g., control-plane config injection inside an MCP server), keep the import **localized inside the calling function or method**, never at module level.

---

## 3. Test Structure & Classification

Mirror the source tree under `tests/` split strictly by execution speed and runtime boundaries:

```text
tests/
  conftest.py                     # Root shared fixtures, fake adapters, and test configuration
  fixtures/                       # Static mock payloads and JSON fixtures
  unit/                           # Fast, isolated tests with zero live I/O
    adapters/                     # Mirrors src/<app>/adapters/
    configuration/                # Mirrors src/<app>/configuration/
    infrastructure/               # Mirrors src/<app>/infrastructure/
    models/                       # Mirrors src/<app>/models/
    services/                     # Mirrors src/<app>/services/
    mcp/                          # Fast MCP surface/schema tests
    bdd/                          # Pytest tests of BDD harness hooks and steps
  integration/                    # Tests touching real SQLite, migrations, or multi-module transport
    routers/                      # FastAPI endpoint workflows with real/in-memory dependencies
    persistence/                  # SQLite storage repositories and Alembic migrations
    services/                     # Services exercising real persistence or OAuth flows
    mcp/                          # Full MCP server runtime lifecycle tests
    adversarial/                  # Security, leakage, and adversarial lifecycle test suites
  bdd/
    features/
      *.feature                   # Gherkin scenario files
      environment.py              # Scenario lifecycle hooks
      steps/
        *.py                      # Shared step definition modules
```

### Classification Criteria
- **Unit (`tests/unit/`)**: Fast and fully isolated. External SDKs, HTTP calls, and database sessions are mocked/stubbed.
- **Integration (`tests/integration/`)**: Uses a real SQLite database, executes Alembic migrations, or tests complete FastAPI/MCP transport lifecycles. If any test in a module touches real integration boundaries, classify the module under `integration/`.
- **Mirroring Convention**: Name test files after the module they test (`src/freesearch/services/routing.py` $\rightarrow$ `tests/unit/services/test_routing.py`).

---

## 4. Mocking & Path Seams

- **Mock at the Consumer Lookup Site**: Always patch symbols where they are *imported and used*, not where they are defined.
  - *Correct*: `patch("freesearch.routers.api.build_adapters")`
  - *Incorrect*: `patch("freesearch.mcp.server.build_adapters")`
- **Stable Path Resolution**: Never calculate file paths using brittle relative levels. Always anchor using `Path(__file__).resolve().parents[N]` matched to directory depth, or use `Path.cwd()` when resolving workspace paths.

---

## 5. Pre-Commit Verification Checklist

When adding new modules, moving code, or updating package boundaries, run:

- [ ] New source modules placed in the appropriate `src/<app>/<package>/` subpackage.
- [ ] Any new subpackage includes an `__init__.py` file.
- [ ] No circular imports introduced at module scope.
- [ ] Unit tests placed in `tests/unit/<package>/` mirroring source layout.
- [ ] Tests touching DB/migrations or app lifecycles placed in `tests/integration/<package>/`.
- [ ] Mock patches target consumer lookup sites.
- [ ] Verification suite passes:
  ```powershell
  uv run ruff check src tests
  uv run mypy
  uv run pytest tests/unit
  uv run pytest tests/integration
  ```
