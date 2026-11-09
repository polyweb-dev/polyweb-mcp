import { expect } from "@playwright/test"
import { Given, When, Then } from "./fixtures"
import { providerQuotaSurface } from "./providerQuotaUi"
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
  // The balance dialog opens from the `…` menu of the card that holds this provider's logo.
  const card = providerQuotaSurface(page, provider === "brave" ? "Brave" : provider)
  await card.getByRole("button", { name: /^Actions for /i }).click()
  await page.getByRole("button", { name: "Set balance", exact: true }).click()
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

Then("the usage view offers no OAuth pairing control", async ({ page }) => {
  // Pairing happens on the vault page, not inside the quota view.
  const main = page.locator("main")
  await expect(main.getByTestId(/^oauth-device-/)).toHaveCount(0)
  await expect(main.getByRole("button", { name: /^(Connect|Pair|Disconnect)\b/ })).toHaveCount(0)
  await expect(main.getByTestId("oauth-user-code")).toHaveCount(0)
})

Then("Quotas links to Keys and pools for Parallel", async ({ page }) => {
  await expect(page.getByRole("link", { name: "Keys and pools", exact: true }))
    .toHaveAttribute("href", "/account/keys")
})
