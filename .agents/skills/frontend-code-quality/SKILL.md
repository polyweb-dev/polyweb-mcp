---
name: frontend-code-quality
description: "Audit architecture boundaries, circular imports, dead code, unused exports, cyclomatic complexity, nesting depth, and TypeScript type safety in freesearch-ui/src. Use when you verify PR readiness, review code changes, diagnose dependency-cruiser violations, fix ESLint complexity errors, or resolve Knip unused export and dependency reports."
---

# Code Quality & Static Analysis

Enforces architectural boundaries, dead-code elimination, cyclomatic complexity limits, and TypeScript type safety across `freesearch-ui/src`.

## 1. Audit Pipeline

**Workflow**: `pnpm depcruise` ──> `pnpm knip` ──> `pnpm lint` ──> `pnpm typecheck`

Run each command from `freesearch-ui/`:

```powershell
pnpm depcruise
pnpm knip
pnpm lint
pnpm typecheck
```

---

## 2. Tools & Rule Matrix

| Tool | Focus Area | Inner-Loop / Targeted Check | Full Command | Config File |
| :--- | :--- | :--- | :--- | :--- |
| **Dependency Cruiser** | Circular imports & resolvable paths | `pnpm depcruise` | `pnpm depcruise` | `.dependency-cruiser.cjs` |
| **Knip** | Dead code, unused exports/deps | `pnpm knip` | `pnpm knip` | `knip.json` |
| **ESLint** | Complexity (≤12), nesting, style | `npx eslint <target-file>` | `pnpm lint` | `eslint.config.js` |
| **TypeScript** | Strict compile-time type verification | `npx tsc --noEmit -p tsconfig.vitest.json` | `pnpm typecheck` | `tsconfig.vitest.json` |

---

## 3. Core Boundary Rules & Budgets

`.dependency-cruiser.cjs` declares three rules:

* **`no-circular`**: Zero circular dependencies allowed. A circular dependency causes runtime init faults and broken HMR.
* **`not-to-unresolvable`**: Every import must resolve. This rule catches broken paths and absent packages.
* **`no-orphans`**: This rule warns on each file that no other file imports.
* **Complexity Budget**: Max cyclomatic complexity is 12, max nesting depth is 4, and max lines per function is 100 (disabled for test suites).

---

## 4. Troubleshoot Predictably

| Symptom | Cause | Action |
| :--- | :--- | :--- |
| **`not-to-unresolvable` error** | An import path is broken or a package is absent | Correct the import path or install the package. |
| **`no-circular` error** | Two files import each other's types/values | Extract shared types or utility functions into a dedicated sub-module. |
| **Knip flags generated files** | Test or coverage output detected as unreferenced files | Keep the generated specs in `tests/features-gen/` outside the `project` globs in `knip.json`. |
| **ESLint complexity warning (>12)** | Deep branching with multiple `if/else`, `switch`, or `&&/\|\|` | Replace compound conditionals with lookup tables, state machines, or helper extraction. |

---

## 5. Review Checklist

- [ ] `pnpm depcruise` exits 0 (`✔ no dependency violations found`).
- [ ] `pnpm knip` exits 0 (0 unused files, exports, or deps).
- [ ] `pnpm lint` exits 0 (0 errors, 0 warnings).
- [ ] `pnpm typecheck` exits 0 across `freesearch-ui/src`.
