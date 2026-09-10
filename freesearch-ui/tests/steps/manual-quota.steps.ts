import { expect } from "@playwright/test"
import { Given, When, Then } from "./fixtures"
import { setStubbedManualQuota } from "./backendStub"

/**
 * Manual billing entry (provider-quota-display.feature @manual). The stubbed
 * backend serves GET/PUT/DELETE /api/v1/providers/{id}/manual-quota from
 * per-scenario in-memory state; the saved window renders as an estimated
 * overlay beside the untouched vendor throttle headline.
 */

Given("the stubbed manual quota for {string} is empty", async ({}, provider: string) => {
  setStubbedManualQuota(provider, null)
})

Given(
  "the stubbed manual quota for {string} allows {string} with usage {string} from {string} to {string}",
  async ({}, provider: string, allowance: string, used: string, start: string, end: string) => {
    setStubbedManualQuota(provider, {
      provider,
      billing_start: start,
      billing_end: end,
      allowance,
      current_usage: used,
    })
  }
)

When("I open the manual budget entry for provider {string}", async ({ page }, provider: string) => {
  await page.getByTestId("manual-quota-open-" + provider).click()
  await expect(page.getByTestId("manual-quota-save")).toBeVisible()
})

When(
  "I enter the manual billing window {string} to {string} with allowance {string} and usage {string}",
  async ({ page }, start: string, end: string, allowance: string, usage: string) => {
    await page.getByTestId("manual-quota-start").fill(start)
    await page.getByTestId("manual-quota-end").fill(end)
    await page.getByTestId("manual-quota-allowance").fill(allowance)
    await page.getByTestId("manual-quota-usage").fill(usage)
  }
)

When("I save the manual budget entry", async ({ page }) => {
  await page.getByTestId("manual-quota-save").click()
})

Then(
  "the manual overlay progress bar for provider {string} should show {string}",
  async ({ page }, provider: string, value: string) => {
    const bar = page
      .getByTestId("manual-quota-estimate-" + provider)
      .getByRole("progressbar")
    await expect(bar).toHaveAttribute("aria-valuenow", value)
  }
)
