import { expect } from "@playwright/test"
import { When, Then } from "./fixtures"

/**
 * Live provider smoke steps (test-only, @live scenarios only).
 *
 * The default @stub suite installs the deterministic backend stub via the
 * fixtures Before hook; @live scenarios carry neither @stub nor @visual so
 * they reach the real backend through the Vite proxy. These steps are
 * STRICT: unlike the stub-tolerant "results or an error banner"
 * assertions, live smoke requires rendered results/content AND zero
 * API-failure alerts. First-outcome capture steps never fail — they poll
 * for either terminal surface and log a single LIVE-FIRST-* line so the
 * first-fails-second-succeeds pattern is visible per provider.
 */

const ERROR_RE = /unreachable|failed|error|unavailable|no provider|timed out|timeout/i

/**
 * Project of the live run (U2: the playground and Activity are project
 * sections). Name it with FREESEARCH_E2E_PROJECT; the local seed script
 * creates "Local E2E".
 */
const LIVE_PROJECT_NAME = process.env.FREESEARCH_E2E_PROJECT ?? "Local E2E"

When("I open the projects list", async ({ page }) => {
  await page.goto("/projects")
  await expect(page.getByRole("heading", { name: "Projects", exact: true })).toBeVisible({
    timeout: 15_000,
  })
})

When("I choose the live e2e project in the project selector", async ({ page }) => {
  await page.getByRole("button", { name: /^Select project/ }).first().click()
  await page.getByRole("menuitem", { name: LIVE_PROJECT_NAME, exact: false }).first().click()
  await expect(page).toHaveURL(/\/p\/[0-9a-f-]{36}/, { timeout: 15_000 })
  await expect(
    page.getByRole("button", { name: `Select project (current: ${LIVE_PROJECT_NAME})` })
  ).toBeVisible({ timeout: 15_000 })
})

function searchErrorBanner(page: import("@playwright/test").Page) {
  return page.locator("main").locator('p[style*="status-danger"]', { hasText: ERROR_RE })
}

function fetchErrorBanner(page: import("@playwright/test").Page) {
  return page.locator("main").locator('p[style*="status-danger"]', { hasText: ERROR_RE })
}

When(
  "I capture the first live search outcome for provider {string}",
  async ({ page }, provider: string) => {
    const panel = page.locator("main")
    const results = panel.getByText(/% match/i)
    const errors = searchErrorBanner(page)
    const deadline = Date.now() + 30_000
    let outcome = "indeterminate"
    while (Date.now() < deadline) {
      const [resultCount, errorCount] = await Promise.all([
        results.count(),
        errors.count(),
      ])
      if (resultCount > 0 && errorCount === 0) {
        outcome = "results"
        break
      }
      if (errorCount > 0) {
        outcome = "api-failure"
        break
      }
      await page.waitForTimeout(500)
    }
    console.log(`LIVE-FIRST-SEARCH provider="${provider}" outcome=${outcome}`)
  }
)

When(
  "I capture the first live fetch outcome for provider {string}",
  async ({ page }, provider: string) => {
    const panel = page.locator("main")
    const content = panel.getByText(/Parsed Markdown Document/i)
    const errors = fetchErrorBanner(page)
    const deadline = Date.now() + 30_000
    let outcome = "indeterminate"
    while (Date.now() < deadline) {
      const [contentCount, errorCount] = await Promise.all([
        content.count(),
        errors.count(),
      ])
      if (contentCount > 0 && errorCount === 0) {
        outcome = "content"
        break
      }
      if (errorCount > 0) {
        outcome = "api-failure"
        break
      }
      await page.waitForTimeout(500)
    }
    console.log(`LIVE-FIRST-FETCH provider="${provider}" outcome=${outcome}`)
  }
)

Then(
  "the playground should show live search results without an API-failure alert",
  async ({ page }) => {
    const panel = page.locator("main")
    await expect(panel.getByText(/% match/i).first()).toBeVisible({ timeout: 30_000 })
    await expect(searchErrorBanner(page)).toHaveCount(0)
  }
)

Then(
  "the playground should show live fetch content without an API-failure alert",
  async ({ page }) => {
    const panel = page.locator("main")
    await expect(panel.getByText(/Parsed Markdown Document/i).first()).toBeVisible({
      timeout: 30_000,
    })
    await expect(fetchErrorBanner(page)).toHaveCount(0)
  }
)
