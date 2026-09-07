import { expect } from "@playwright/test"
import { When, Then } from "./fixtures"

/**
 * Live-backend playground search: the app POSTs /search through the vite
 * proxy, so the suite accepts either mapped results or an honest error
 * banner — never invented multi-hop waterfall text.
 */
When("I submit the playground search query {string}", async ({ page }, query: string) => {
  await page
    .getByPlaceholder(/Search across all providers/i)
    .fill(query)
  await page.getByRole("button", { name: "Search", exact: true }).click()
})

Then("the playground should show search results or an error banner", async ({ page }) => {
  // Scoped branches (strict-mode safe): results match inside the results
  // list, errors match only the search panel's error banner element — never
  // tooltips, titles, or hidden text elsewhere on the page.
  const panel = page.locator("main")
  const results = panel.getByText(/% match/i)
  const errorBanner = panel.locator('p[style*="status-danger"]', {
    hasText: /unreachable|failed|error|unavailable|no provider|timed out|timeout/i,
  })
  await expect(async () => {
    const resultCount = await results.count()
    const errorCount = await errorBanner.count()
    expect(resultCount + errorCount).toBeGreaterThan(0)
  }).toPass({ timeout: 15_000 })
})

Then("the playground should not show multi-hop fallback text", async ({ page }) => {
  const body = await page.locator("body").innerText()
  expect(body).not.toMatch(/[2-9]\d* hops evaluated/)
})
