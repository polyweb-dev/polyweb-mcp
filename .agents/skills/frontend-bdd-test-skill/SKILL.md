---
name: frontend-bdd-test-skill
description: "Author, maintain, and execute end-to-end BDD tests for React web applications using Playwright-BDD, TypeScript, and Gherkin feature files. Use when adding acceptance scenarios, generating test specs with bddgen, running browser tests, diagnosing E2E failures, or creating typed step definitions."
---

# Playwright-BDD for React & TypeScript

End-to-end Behavior-Driven Development (BDD) using `playwright-bdd`, TypeScript, and Gherkin (`.feature`) files.

## 1. Workflow & Commands

Run each command from `freesearch-ui/`.

**Workflow**: Write `.feature` ──> Implement step definitions in `tests/steps/*.ts` ──> `pnpm bddgen` ──> `pnpm test:e2e`

Run `pnpm bddgen` before each direct `npx playwright test` command. The generated specs in `tests/features-gen/` must agree with the current `.feature` files.

* **Inner Loop (Active Development)**: Run only the scenario under test:
  ```bash
  pnpm bddgen && npx playwright test --grep "@smoke"
  ```
* **Full Suite Execution**:
  ```bash
  pnpm test:e2e          # Runs bddgen and executes full test matrix
  pnpm test:e2e:headed   # Runs bddgen and executes the matrix in headed mode
  ```
* **Debugging**:
  ```bash
  npx playwright test --debug
  npx playwright show-report
  ```

---

## 2. Directory Structure (`freesearch-ui`)

```
freesearch-ui/
├── playwright.config.ts          # defineBddConfig & webServer config
└── tests/
    ├── features/                 # Declarative Gherkin (.feature) files
    ├── features-gen/             # Generated specs from bddgen (never edit by hand)
    └── steps/                    # Step definitions & fixtures
        ├── fixtures.ts           # Extended Playwright test & createBdd export
        └── *.steps.ts            # Typed Given, When, Then definitions
```

---

## 3. Implementation Patterns

### Centralized Fixtures (`tests/steps/fixtures.ts`)
```typescript
import { test as base, createBdd } from "playwright-bdd";

export const test = base.extend<{ /* custom Page Objects / fixtures */ }>({
  // fixture implementations
});

export const { Given, When, Then, Step, Before, After, BeforeAll, AfterAll } =
  createBdd(test);
```

### Declarative Gherkin (`tests/features/workspace.feature`)
```gherkin
Feature: Workspace Management
  Background:
    Given I navigate to the web application

  @smoke
  Scenario: Submitting a prompt in the active thread
    When I type "Verify deployment pipeline status" into the composer textarea
    Then the composer textarea should contain "Verify deployment pipeline status"
```

### TypeScript Step Definitions (`tests/steps/workspace.steps.ts`)
```typescript
import { expect } from "@playwright/test";
import { Given, When, Then } from "./fixtures";

Given("I navigate to the web application", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".app-shell")).toBeVisible();
});

When("I type {string} into the composer textarea", async ({ page }, text: string) => {
  await page.locator(".composer-shell textarea").fill(text);
});

Then("the composer textarea should contain {string}", async ({ page }, text: string) => {
  await expect(page.locator(".composer-shell textarea")).toHaveValue(text);
});
```

---

## 4. Troubleshoot Predictably

| Symptom | Cause | Action |
| :--- | :--- | :--- |
| **"Missing step definition" error** | Gherkin text does not match step pattern or `bddgen` not regenerated | Run `pnpm bddgen` to regenerate `tests/features-gen/`; check parameter quotes `{string}` vs `{int}`. |
| **Flaky or timing out element** | Using fixed `waitForTimeout` or missing auto-wait assertion | Use auto-waiting assertions: `await expect(locator).toBeVisible()` or semantic `page.getByRole(...)`. |
| **Port busy or connection refused** | A dev server uses the port, or no dev server runs | Do the worktree port check and the server identity check in Section 5. |
| **Stale test runner artifacts** | Cached `tests/features-gen/` specs from deleted feature files | Delete the `tests/features-gen/` directory and re-run `pnpm bddgen`. |

---

## 5. Best Practices & Rules

- **Declarative Scenarios**: Write user-intent focused scenarios (`When I submit valid credentials`), not low-level DOM keystrokes.
- **Auto-Waiting Locators**: Rely on auto-waiting assertions (`await expect(locator).toBeVisible()`). Never use hardcoded sleeps (`page.waitForTimeout()`).
- **Worktree Port Check**: Read `VITE_PORT` from the local `.env` before you start a server. Confirm that the port belongs to your worktree.
- **Server Identity Check**: Confirm the identity of each running server. Run e2e tests only against the server of your own worktree.
- **Clean Git Artifacts**: Keep `tests/features-gen/`, `test-results/`, and `playwright-report/` in `.gitignore`.
