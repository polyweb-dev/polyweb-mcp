---
name: backend-bdd-test-skill
description: "Author, maintain, and execute Behavior-Driven Development (BDD) tests in Python using Behave and Gherkin feature files. Use when adding acceptance scenarios, writing typed step definitions, using Scenario Outlines and DataTables, managing environment.py async lifecycle hooks, generating step skeletons, or diagnosing Behave test failures."
---

# Behave (Cucumber) BDD Skill for Python

Systematic Behavior-Driven Development (BDD) testing in Python using **Behave** (`behave`) and **Gherkin (`.feature`) files**.

## 1. Execution Path: Choose the Lightest Path

**Workflow**: `Write .feature ──> uv run behave --dry-run (skeletons) ──> Implement tests/bdd/features/steps/*.py ──> uv run behave`

* **Inner Loop (Active Development / Single Scenario)**:
  ```bash
  uv run behave tests/bdd/features/brave.feature   # Run specific feature file
  uv run behave tests/bdd/features/quota.feature   # Run another feature file
  uv run behave --tags=@smoke                      # Run specific tag
  ```
* **Step Skeleton Discovery (Code Generation)**:
  ```bash
  uv run behave --dry-run                        # Prints missing @given/@when/@then snippets
  ```
* **Live Run with Console Output**:
  ```bash
  uv run behave --no-capture                     # Disables stdout/stderr capture during execution
  ```
* **Outer Loop (Full Suite & CI Reporting)**:
  ```bash
  uv run behave --junit --junit-directory=coverage/behave/
  ```

---

## 2. Directory Structure & File Conventions

```
tests/bdd/features/
├── environment.py              # Global & scenario lifecycle hooks (setup/teardown)
├── brave.feature               # Declarative Gherkin feature specifications
├── quota.feature
└── steps/                      # Python step definitions
    ├── brave_steps.py          # @given, @when, @then step implementations
    └── quota_steps.py
```

`pyproject.toml` sets `[tool.behave] paths = ["tests/bdd/features"]`. Do not place feature files in a root `features/` directory.

---

## 3. Gherkin Feature Design Patterns

### 1. Basic Scenario with Typed Parameters
```gherkin
Feature: Provider Routing & Fallbacks
  As an API consumer
  I want queries routed to healthy providers
  So that service availability is maximized

  Background:
    Given a running routing engine

  @smoke
  Scenario: Route query to primary provider
    When I submit a search request for "Python async" with limit 5
    Then the active provider should be "tavily"
    And the returned result count should be 5
```

### 2. Scenario Outlines with Parameter Matrices
```gherkin
  Scenario Outline: Cost estimation across operations
    When I estimate cost for "<operation>" on "<provider>"
    Then the calculated credits should be <expected_credits>

    Examples:
      | operation | provider | expected_credits |
      | search    | tavily   | 1.0              |
      | fetch     | tavily   | 0.2              |
      | search    | exa      | 1.0              |
```

### 3. DataTables & Multiline DocStrings
```gherkin
  Scenario: Batch provider configuration
    Given the following provider registry:
      | provider | priority | enabled |
      | tavily   | 1        | true    |
      | exa      | 2        | true    |
      | brave    | 3        | false   |
    When I initialize the multi-provider router
    Then only 2 providers should be active
```

---

## 4. Step Implementations & Async Handling

### Typed Step Matchers (`tests/bdd/features/steps/*.py`)
Behave supports parse formatters: `{name}` (str), `{limit:d}` (int), `{cost:f}` (float), `{word:w}` (single word).

```python
from decimal import Decimal
from typing import Any
from behave import given, when, then  # type: ignore[import-untyped]


@given("a running routing engine")
def step_given_engine(context: Any) -> None:
    context.engine = getattr(context, "engine", None) or create_engine()


@when('I submit a search request for "{query}" with limit {limit:d}')
def step_when_search(context: Any, query: str, limit: int) -> None:
    # Handle async calls via scenario event loop:
    context.response = context.loop.run_until_complete(
        context.engine.search(query=query, limit=limit)
    )


@then('the active provider should be "{expected_provider}"')
def step_then_provider(context: Any, expected_provider: str) -> None:
    assert context.response.provider == expected_provider


@then("the returned result count should be {count:d}")
def step_then_count(context: Any, count: int) -> None:
    assert len(context.response.results) == count
```

### Handling DataTables in Python
```python
@given("the following provider registry:")
def step_given_table(context: Any) -> None:
    # Iterate table rows as dicts:
    for row in context.table:
        provider = row["provider"]
        priority = int(row["priority"])
        enabled = row["enabled"].lower() == "true"
        context.engine.register(provider, priority=priority, enabled=enabled)
```

---

## 5. Environment Lifecycle Hooks (`tests/bdd/features/environment.py`)

Manage async event loops, client sessions, database connections, and cleanup:

```python
import asyncio
from typing import Any
import httpx


def before_all(context: Any) -> None:
    """Run once before any feature runs (e.g. test database init)."""
    context.config_data = {}


def before_scenario(context: Any, scenario: Any) -> None:
    """Isolate async event loop and HTTP sessions per scenario."""
    context.loop = asyncio.new_event_loop()
    asyncio.set_event_loop(context.loop)
    context.http_client = httpx.AsyncClient(timeout=30.0)


def after_scenario(context: Any, scenario: Any) -> None:
    """Clean up open client connections and close the scenario event loop."""
    if getattr(context, "http_client", None) is not None:
        context.loop.run_until_complete(context.http_client.aclose())
    if getattr(context, "loop", None) is not None:
        context.loop.close()


def before_tag(context: Any, tag: str) -> None:
    """Execute setup only for specific tags (e.g. @database, @live)."""
    if tag == "live" and not getattr(context, "has_credentials", True):
        context.scenario.skip("Live credentials not available")
```

---

## 6. Troubleshoot Predictably

| Symptom | Cause | Action |
| :--- | :--- | :--- |
| **"Undefined Step" error** | Gherkin text does not match step decorator pattern | Run `uv run behave --dry-run` to print the exact template decorator; verify parameter types (`{limit:d}` vs `{text}`). |
| **`RuntimeError: Event loop is closed`** | Async task invoked outside active scenario loop | Wrap all async service/adapter calls with `context.loop.run_until_complete()`. |
| **State Leaks Between Scenarios** | Objects attached to `context` surviving scenario end | Reset scenario attributes in `before_scenario` or rely on `after_scenario` teardown. |
| **Step Times Out on External Network** | Default HTTP timeout exceeded | Set explicit timeout on `httpx.AsyncClient(timeout=30.0)` in `environment.py`. |
| **Skipped Scenarios not Printing Details** | Default output hides skipped step reasons | Run with `uv run behave --show-skipped` or `--no-skipped` as needed. |

---

## 7. Best Practices & Rules

- **Declarative over Imperative**: Express user value and business behavior (`When I route search request`), not UI click sequences or low-level variable assignments.
- **Tagging Strategy**: Tag scenarios by area (`@search`, `@routing`, `@storage`, `@mcp`) and test speed (`@unit`, `@live`, `@smoke`) for flexible CI execution.
- **Isolate Scenarios**: Scenarios must never depend on the execution order or side-effects of preceding scenarios.
- **Exempt from Complexity Rules**: `pyproject.toml` contains `per-file-ignores` for `tests/**` (`C901`) to support multi-step validation flows.
- **Never Run Mutation Tests on BDD**: Mutation testing targets pure, fast unit tests (`tests/`), never end-to-end BDD suites.
