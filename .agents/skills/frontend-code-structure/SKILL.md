---
name: frontend-code-structure
description: "Guidelines and conventions for frontend module boundaries, feature/domain separation, component extraction, state management, layer conventions, and test organization. Use when you create UI components, refactor React code, structure features, or audit frontend boundaries."
---

# Frontend Code Structure & Architecture Guidelines

A modular, feature-and-domain driven React architecture designed to prevent monolithic contexts, maintain strict dependency boundaries, and ensure sustainable component growth.

---

## 1. Target Architectural Layers & Responsibilities (`freesearch-ui/src/`)

```text
src/
  app/                 # Application bootstrap, routing table, shell layout, provider composition
    layout/            # Shell components (DashboardShell, Sidebar, StatusBar)
    AppProviders.tsx   # Composition of domain-level providers
    routes.ts          # Route definitions and navigation paths
  domains/             # Core business models, data ownership, and domain APIs
    providers/         # Provider catalog, credentials, statuses, priorities, commands
    routing/           # Routing configuration, policies, and simulation algorithms
    dashboard/         # Usage statistics, telemetry snapshots, and quota ledgers
    execution/         # Search & fetch commands, result mapping, error states
  features/            # User-facing feature modules (screen sections and workflows)
    playground/        # Search execution playground, request options, waterfall viewer
    routing/           # Routing rule management, strategy toggles, route visualizer
    quota/             # Quota analytics dashboard, limit alerts, manual quota modal
    activity/          # Execution log stream, event inspection, activity filters
    settings/          # Provider configuration, API key vault, environment status
    oauth/             # OAuth pairing dialogs, lifecycle polling, balance monitors
  shared/              # Business-agnostic, reusable primitives and infrastructure
    ui/                # Reusable dumb UI components (Button, Dialog, Input, PillTabs)
    api/               # HTTP client abstraction, fetch error normalization
    notifications/     # Toast system and status alerts
    lib/               # Generic utility helpers (date formatting, math)
  test/                # Shared test fixtures, MSW/fetch mock handlers, test renderers
tests/                 # Cross-feature browser BDD scenarios (Gherkin, Playwright steps, snapshots)
```

This layout is the target architecture. Parts of it are not in place yet. Treat each path in this section as the goal for new code.

### Layer Ownership Matrix

| Layer | Responsibility | What It May Import | What Must Never Enter |
| :--- | :--- | :--- | :--- |
| **`app/`** | Shell composition, top-level routing, root providers. | `features/`, `domains/`, `shared/` | Feature-internal private helpers |
| **`features/`** | User workflows, page views, cohesive dialogs. | `domains/` (public API), `shared/` | **Other `features/`** (no feature-to-feature imports) |
| **`domains/`** | Business logic, state stores, wire-to-domain mappers. | `shared/` | `features/`, `app/`, other `domains/` (by default) |
| **`shared/ui`** | Pure design-system components and accessible primitives. | Other `shared/` primitives | Business models, domain types, API clients |
| **`shared/api`** | Transport setup, status codes, abort signals. | Generic types, `shared/lib` | Domain entities, provider catalogs |

---

## 2. Dependency & Import Rules

The layer bounds in this section are conventions. Dependency Cruiser does not declare them. The tool declares only three rules: `no-circular`, `not-to-unresolvable`, and `no-orphans`. ESLint enforces the size and nesting budgets in Section 4. Review the layer bounds during code review.

1. **Unidirectional Import Flow**:
   $$\text{app} \longrightarrow \text{features} \longrightarrow \text{domains} \longrightarrow \text{shared}$$
2. **No Feature-to-Feature Coupling**:
   - If `Feature A` needs to trigger a dialog or view from `Feature B`, compose them at the `app/` level using composition slots (`children` / render props) or coordinate through a shared `domain/`.
3. **Domain Isolation**:
   - Domains should not cross-import. If domain data must be combined (e.g., joining provider metadata with dashboard quota usage), create an app-level composition selector or pass values via typed function arguments.
4. **Public Barrel Discipline**:
   - Import external modules strictly via their top-level `index.ts` public contract.
   - **Never** import your own module through its own barrel file (prevents cyclic initialization).
5. **No Test Imports in Production**:
   - Production code must never import from `src/test/` or `tests/`.

---

## 3. Component & State Architecture

### Component Anatomy: Split by Responsibility
Avoid multi-hundred-line monolithic files. Within a feature or domain:
- **`ui/`**: Cohesive presentational components. Describes what the screen looks like.
- **`model/`**: Custom hooks (controllers), state stores, and pure calculation helpers.
- **`api/`**: Endpoint call wrappers, wire DTOs, and response decoders.

### State Rules
1. **Narrow Domain Providers**: Avoid a single mega-context. Split state by domain (`ProviderContext`, `RoutingContext`, `DashboardContext`).
2. **Colocate Ephemeral State**: Keep form draft inputs, tab selections, row expansions, and modal visibility in the local component or a feature controller hook (`usePlaygroundController.ts`).
3. **Derive, Don't Sync**: Calculate view data during render rather than duplicating upstream state into local `useEffect` synchronizations.
4. **Node & Focus Identity**: When switching views (e.g., hero search bar docking into header), preserve DOM node identity and focus state rather than unmounting and replacing elements.
5. **One Component per File**: Keep each file focused on a single named export (compound UI primitives in `shared/ui` are exempt).

---

## 4. Code Budgets & Type Safety

### Lint & Complexity Budgets
- **Max File Length**: 300 physical lines (excluding comments).
- **Max Function Length**: 100 lines.
- **Max Cyclomatic Complexity**: $\le 12$ branches.
- **Max Nesting Depth**: $\le 4$ levels.
- **Max Function Parameters**: $\le 4$ parameters (use option objects for more).

### Strict Typing Guidelines
- **External Data is Unknown**: Treat incoming API payloads as `unknown`; decode/validate through domain mappers before consuming in view models.
- **Guard Array Access**: Always guard index lookups (`const item = list[i]; if (!item) return;`).
- **Discriminated Unions**: Model mutually exclusive states (e.g., async status: `idle | loading | success | error`, OAuth pairing phases) with tagged unions to eliminate illegal state combinations.
- **No Blanket `any`**: Use `satisfies` and explicit mock types; avoid type assertions (`as SomeType`) without verification.

---

## 5. Test Organization & Preservation

1. **Colocated Unit & Component Tests**:
   - Place Vitest component and hook tests directly alongside the implementation (`PlaygroundPage.tsx` $\rightarrow$ `PlaygroundPage.test.tsx`).
2. **Robust Semantic Selectors**:
   - Query by user-facing roles and accessibility labels (`getByRole("button", { name: /save/i })`, `getByLabelText`).
   - Avoid brittle DOM structure queries (e.g., `container.querySelector("div.grid > div.border")`).
3. **Cross-Feature BDD / E2E**:
   - Full user journeys and visual regression checks live in `tests/features/` and `tests/steps/`.
4. **Characterization Before Refactoring**:
   - Before extracting or refactoring complex flows (e.g., OAuth polling, priority rollback, optimistic telemetry), write a characterization test locking in current behavior.

---

## 6. Pre-Commit Verification Checklist

Before you open a PR or complete a frontend refactoring slice, run these commands from `freesearch-ui/`:

- [ ] New components placed in the appropriate `features/`, `domains/`, or `shared/` layer.
- [ ] No direct feature-to-feature or illegal upward imports.
- [ ] Reusable UI components in `shared/ui` contain zero business logic or domain types.
- [ ] File and function lengths meet ESLint budgets ($\le 300$ file lines, $\le 12$ complexity).
- [ ] Audit pipeline passes completely:
  ```powershell
  pnpm depcruise
  pnpm knip
  pnpm lint
  pnpm typecheck
  pnpm test
  ```
