import { test as base, createBdd } from "playwright-bdd"
import { installBackendStub } from "./backendStub"

/**
 * Keep the BDD fixture surface in one place so every generated scenario uses
 * the same Playwright test instance and the shared browser context.
 */
export const test = base.extend({})

export const { Given, When, Then, Before, After } = createBdd(test)

/**
 * State-neutrality guard: stubbed scenarios serve the backend from fixed
 * in-memory fixtures (see backendStub.ts) instead of the live backend at
 * 127.0.0.1:8001. Writes inside the scenario (routing PUT, secret PUT/DELETE,
 * provider PATCH) stay in memory — the real backend is never mutated, and
 * screenshots/counts render from deterministic state.
 *
 * Tagging contract: `@visual` marks screenshot/keyboard scenarios, `@stub`
 * marks stubbed non-visual scenarios. Live-integration coverage stays real:
 * the playground live-search and activity-privacy scenarios carry neither tag.
 */
Before({ tags: "@visual or @stub" }, async ({ page }) => {
  await installBackendStub(page)
})
