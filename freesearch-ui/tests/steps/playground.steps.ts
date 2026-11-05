import { expect } from "@playwright/test"
import { Given, When, Then } from "./fixtures"
import {
  braveObservedQuota,
  keenableKeylessQuota,
  overrideDashboardLatestQuota,
  parallelPairedQuota,
  parallelSeededQuota,
  parallelUnseededQuota,
} from "./backendStub"

/**
 * Live-backend playground search: the app POSTs /search through the vite
 * proxy, so the suite accepts either mapped results or an honest error
 * banner — never invented multi-hop waterfall text.
 */
When("I submit the playground search query {string}", async ({ page }, query: string) => {
  await page
    .getByPlaceholder(/Search the web/i)
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

/**
 * Stubbed provider search/fetch (provider-search-fetch.feature) and honest
 * quota display (provider-quota-display.feature). All backend traffic is
 * served by the deterministic stub; assertions use exact visible strings.
 */

When("I pin the playground provider to {string}", async ({ page }, provider: string) => {
  const trigger = page.getByTestId("playground-search-provider")
  await expect(trigger).toBeVisible()
  await trigger.click()
  await page.getByRole("option", { name: provider }).click()
})

When(
  "I pin the playground fetch provider to {string}",
  async ({ page }, provider: string) => {
    const trigger = page.getByTestId("playground-fetch-provider")
    await expect(trigger).toBeVisible()
    await trigger.click()
    await page.getByRole("option", { name: provider }).click()
  }
)

When("I submit the playground fetch URL {string}", async ({ page }, url: string) => {
  await page.getByPlaceholder(/URL to fetch/i).fill(url)
  await page.getByRole("button", { name: "Fetch", exact: true }).click()
})

Then("the playground should show fetch content or an error banner", async ({ page }) => {
  const panel = page.locator("main")
  const content = panel.getByText(/Parsed Markdown Document/i)
  const errorBanner = panel.locator('p[style*="status-danger"]', {
    hasText: /unreachable|failed|error|unavailable|no provider|timed out|timeout/i,
  })
  await expect(async () => {
    const contentCount = await content.count()
    const errorCount = await errorBanner.count()
    expect(contentCount + errorCount).toBeGreaterThan(0)
  }).toPass({ timeout: 15_000 })
})

Then(
  "the fetch provider picker should not offer {string}",
  async ({ page }, provider: string) => {
    const trigger = page.getByTestId("playground-fetch-provider")
    await expect(trigger).toBeVisible()
    await trigger.click()
    await expect(page.getByRole("listbox")).toBeVisible()
    await expect(page.getByRole("option", { name: provider })).toHaveCount(0)
    await page.keyboard.press("Escape")
  }
)

Given("the stubbed dashboard shows {string}", async ({ page }, kind: string) => {
  if (kind === "Brave observed quota") {
    await overrideDashboardLatestQuota(page, braveObservedQuota())
  } else if (kind === "Parallel seeded quota") {
    await overrideDashboardLatestQuota(page, parallelSeededQuota())
  } else if (kind === "Parallel unseeded quota") {
    await overrideDashboardLatestQuota(page, parallelUnseededQuota())
  } else if (kind === "Parallel paired quota") {
    await overrideDashboardLatestQuota(page, parallelPairedQuota())
  } else if (kind === "Keenable keyless quota") {
    await overrideDashboardLatestQuota(page, keenableKeylessQuota())
  } else {
    throw new Error(`Unknown stubbed dashboard kind: ${kind}`)
  }
})

Then("the usage view should show {string}", async ({ page }, text: string) => {
  await expect(page.locator("main")).toContainText(text, { timeout: 10_000 })
})

Then("the usage view should not show {string}", async ({ page }, text: string) => {
  // Scoped absence: "Budget not configured" stays honest on the Exa row
  // (7-provider table), so only the Parallel row must not show it after
  // pairing. All other strings keep the global main assertion.
  if (text === "Budget not configured") {
    const parallelRow = page.getByRole("row").filter({ hasText: /Parallel/ })
    await expect(parallelRow).toHaveCount(1)
    await expect(parallelRow).not.toContainText(text)
    return
  }
  await expect(page.locator("main")).not.toContainText(text)
})
