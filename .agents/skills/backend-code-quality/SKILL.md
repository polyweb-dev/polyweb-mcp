---
name: backend-code-quality
description: "Review code quality, audit changes, enforce import hygiene, check cyclomatic complexity, scan for dead code, and run static type checking with Ruff and MyPy. Use when you format code, verify type safety, audit before PR submission, or fix lint and type errors across src/freesearch and tests/."
---

# Code Quality & Static Analysis with Ruff & MyPy

Automated code quality auditing, import boundary verification, dead-code detection, cyclomatic complexity checks, and strict type safety verification.

## 1. Execution Path: Choose the Lightest Path

**Audit Pipeline**: `uv run ruff format --check ──> uv run ruff check ──> uv run mypy ──> uv run pytest`

* **Inner Loop (Active Development / Single File)**:
  ```bash
  uv run ruff format src/freesearch/services/routing.py && uv run ruff check src/freesearch/services/routing.py
  ```
* **Fast Typecheck**:
  ```bash
  uv run mypy
  ```
* **Auto-Fix Safe Lint & Format Issues**:
  ```bash
  uv run ruff check --fix && uv run ruff format
  ```
* **Outer Loop (Pre-PR / Full Audit)**:
  ```powershell
  uv run ruff format --check ; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  uv run ruff check ; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  uv run mypy ; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  uv run pytest ; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  ```

---

## 2. Core Guardrails & Rule Sets

| Rule Set | Code | Threshold / Rule | Scope |
| :--- | :--- | :--- | :--- |
| **Cyclomatic Complexity** | `C901` | McCabe Complexity $\le 15$ | `src/` (exempt in `tests/**`) |
| **Strict Type Safety** | MyPy | `strict = true`, no untyped defs, explicit `T \| None` | Workspace-wide (`freesearch`) |
| **Dead Code / Unused Items** | `F401`, `F841` | 0 unused imports or variables | Workspace-wide |
| **Code Simplification** | `SIM`, `B` | Simplify nested conditionals, avoid bug patterns | Workspace-wide |
| **Modern Python 3.12+** | `UP` | Enforce `X \| Y` unions, built-in generic collections (`list[str]`) | Workspace-wide |
| **Import Hygiene** | `I`, `TID` | Deterministic isort ordering, clean boundaries | Workspace-wide |

---

## 3. Troubleshoot Predictably

| Symptom | Cause | Action |
| :--- | :--- | :--- |
| **`C901 ... is too complex (X > 15)`** | Function has too many branches/loops | Extract nested helper functions or replace `if/elif` chains with dictionary dispatch tables. |
| **`RUF023 __slots__ is not sorted`** | `__slots__` tuple elements are out of alphabetical order | Sort tuple items alphabetically: `__slots__ = ("a", "b")`. |
| **`Incompatible return value type`** | Missing explicit `None` handling in union | Use `T \| None` return annotation and guard with `if result is None:` before returning. |
| **`Function is missing a type annotation`** | Untyped parameter or return under strict MyPy | Add explicit type annotations to all parameters and return types (`def f(x: int) -> str:`). |
| **`F401 ... imported but unused`** | Leftover or unreferenced import | Remove unused import or add `# noqa: F401` if required for re-export in `__init__.py`. |
| **`Untyped import error (import-untyped)`** | 3rd-party dependency lacks py.typed marker | Add `# type: ignore[import-untyped]` on the specific import line. |

---

## 4. Checklist

- [ ] `uv run ruff format --check` exits with all files formatted.
- [ ] `uv run ruff check` exits with 0 lint, dead code, or complexity errors.
- [ ] `uv run mypy` exits with 0 type errors across all source files.
- [ ] `uv run pytest` passes 100% of test cases.


