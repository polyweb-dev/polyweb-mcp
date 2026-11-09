---
name: mutation-testing
description: "Evaluate unit test assertion strength, uncover untested edge cases, and run parallel mutation testing with pytest-gremlins. Use when verifying provider adapters, validating contracts/schemas, diagnosing surviving gremlins, strengthening assertions, or auditing test quality across src/polyweb."
---

# Mutation Testing with pytest-gremlins

Measures unit test assertion strength by injecting faults ("gremlins") into Python source code to verify that test suites fail and catch them.

## 1. Execution Path: Choose the Lightest Path

* **Inner Loop (Active Development / Single File)**: Mutate only the module under test for instant feedback:
  ```bash
  uv run pytest --gremlins --gremlin-parallel --gremlin-targets=src/polyweb/routing.py
  ```
* **Diagnose Surviving Gremlin**: Inspect why a specific mutant survived:
  ```bash
  uv run pytest --gremlin-explain=<gremlin_id>
  ```
* **Outer Loop (Pre-PR / Full Suite)**: Run parallel mutation across the entire codebase with caching:
  ```bash
  uv run pytest --gremlins --gremlin-parallel --gremlin-targets=src/polyweb --gremlin-report=console,html,json --gremlin-cache
  ```
  * HTML Report: `coverage/gremlins/index.html`
  * JSON Report: `coverage/gremlins/gremlins.json`

---

## 2. Core Guardrails

* **Unit Tests Only**: Run strictly against fast, deterministic unit tests (`tests/`). **Never** target live network suites or Behave BDD features (`features/`).
* **Evaluation Metric**:
  * Test Fails ──> ✅ Gremlin ZAPPED (Strong assertion)
  * Test Passes ──> ⚠️ Gremlin SURVIVED (Weak assertion or missing boundary test)
* **Quality Standard**: Maintain a **Mutation Score $\ge 90\%$** on core resilience, routing, contracts, and provider adapters.

---

## 3. Interpreting Results & Remediation

| Status | Meaning | Action Needed |
| :--- | :--- | :--- |
| **Zapped** | A unit test failed when mutant was injected. | None. Test caught the defect. |
| **Survived** | Tests passed despite altered logic. | Add an explicit assertion or boundary test case. |
| **Pardoned** | Suppressed via `# gremlin: pardon[reason]`. | Use sparingly for equivalent mutants. |
| **Timeout** | Mutation caused an infinite loop. | Counts as caught. |

### Remediation Pattern:
If a gremlin survives on a boundary check `if max_chars is not None and len(content) > max_chars:`:
```python
# Add a unit test specifically asserting exact boundary lengths and boundary + 1 truncation:
def test_fetch_truncates_at_exact_max_chars_boundary():
    # Test length == max_chars (not truncated)
    assert len(adapter._truncate("abc", max_chars=3)) == 3
    # Test length == max_chars + 1 (truncated)
    assert len(adapter._truncate("abcd", max_chars=3)) == 3
```

---

## 4. Troubleshoot Predictably

| Symptom | Cause | Action |
| :--- | :--- | :--- |
| **Gremlin Survives on Boundary (`>` vs `>=`)** | Test suite only tests nominal values, not boundary edge cases | Add a test case with the exact boundary value (`0`, `max_limit`, empty collection). |
| **Gremlin Survives on Error Mapping** | Test verifies `pytest.raises(Exception)` instead of specific subtype | Assert the exact normalized exception class (e.g. `ProviderOperationError`) and code. |
| **Mutation Run is Slow on Large Modules** | Subprocess invocation overhead on Windows | Add batching: `--gremlin-batch --gremlin-batch-size=15`. |
| **Stale Cache Results** | Cache hit on modified or reverted test logic | Clear cache: `uv run pytest --gremlins --gremlin-clear-cache`. |

---

## 5. Checklist

- [ ] Target isolated unit tests in `tests/`; never live BDD/network suites.
- [ ] Maintain Mutation Score $\ge 90\%$ on resilience, storage, and provider adapters.
- [ ] Ensure `coverage/` and `.gremlins*` remain in `.gitignore`.


