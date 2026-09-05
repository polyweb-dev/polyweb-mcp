---
name: frontend-code-quality
description: "Audit monorepo architecture boundaries, circular imports, dead code, unused exports, cyclomatic complexity, nesting depth, and TypeScript type safety. Use when verifying PR readiness, reviewing code changes, diagnosing boundary violations in packages/ vs apps/, fixing ESLint complexity errors, or resolving Knip unused export/dependency reports."
---

# Code Quality & Static Analysis

Enforces architectural boundaries, dead-code elimination, cyclomatic complexity limits, and TypeScript type safety across the monorepo.

## 1. Audit Pipeline

**Workflow**: `pnpm depcruise` ──> `pnpm knip` ──> `pnpm lint` ──> `pnpm typecheck`

```bash
# Full audit sequence (PowerShell: replace && with ;)
pnpm depcruise && pnpm knip && pnpm lint && pnpm typecheck
```

---

## 2. Tools & Rule Matrix

| Tool | Focus Area | Inner-Loop / Targeted Check | Full Command | Config File |
| :--- | :--- | :--- | :--- | :--- |
| **Dependency Cruiser** | Layer bounds & circular imports | `pnpm depcruise` | `pnpm depcruise` | `.dependency-cruiser.cjs` |
| **Knip** | Dead code, unused exports/deps | `pnpm knip` | `pnpm knip` | `knip.json` |
| **ESLint** | Complexity (≤12), nesting, style | `npx eslint <target-file>` | `pnpm lint` | `eslint.config.js` |
| **TypeScript** | Strict compile-time type verification | `npx tsc --noEmit -p <pkg>` | `pnpm typecheck` | `tsconfig.base.json` |

---

## 3. Core Architectural Rules

* **`no-circular`**: Zero circular dependencies allowed (prevents runtime init and HMR crashes).
* **`no-packages-to-apps`**: `packages/*` must **never** import from `apps/*`. Move shared code to `packages/shared` or inject via adapter interfaces.
* **`contracts-must-be-independent`**: `packages/contracts` must only hold pure schemas/DTOs and never depend on `client-runtime` or `shared`.
* **Complexity Budget**: Max cyclomatic complexity is 12; max nesting depth is 4; max lines per function is 100 (disabled for test suites).

---

## 4. Troubleshoot Predictably

| Symptom | Cause | Action |
| :--- | :--- | :--- |
| **`no-packages-to-apps` error** | Shared package directly imported web/desktop UI code | Move shared logic into `packages/shared` or use an adapter interface. |
| **`no-circular` error** | Two files import each other's types/values | Extract shared types or utility functions into a dedicated sub-module. |
| **Knip flags generated files** | Test/coverage output detected as unreferenced files | Ensure `coverage/**`, `.features-gen/**`, and `dist/**` are listed in `knip.json` ignore. |
| **ESLint complexity warning (>12)** | Deep branching with multiple `if/else`, `switch`, or `&&/\|\|` | Replace compound conditionals with lookup tables, state machines, or helper extraction. |

---

## 5. Review Checklist

- [ ] `pnpm depcruise` exits 0 (`✔ no dependency violations found`).
- [ ] `pnpm knip` exits 0 (0 unused files, exports, or deps).
- [ ] `pnpm lint` exits 0 (0 errors, 0 warnings).
- [ ] `pnpm typecheck` exits 0 across all workspace packages.
