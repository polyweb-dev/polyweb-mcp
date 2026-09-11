import { expect } from "@playwright/test"
import { Given, When, Then } from "./fixtures"
import { setStubbedOAuthFlow } from "./backendStub"

/**
 * Parallel Account-API OAuth pairing (provider-quota-display.feature @oauth).
 * State lives in the shared backendStub OAuth flows: POST device-code
 * answers ABCD-EFGH, status follows the flipped flow state, and pairing
 * flips the row to the authoritative remaining-only USD balance.
 */

Given("the stubbed OAuth pairing for {string} is empty", async ({}, provider: string) => {
  setStubbedOAuthFlow(provider, "unpaired")
})

When("the stubbed OAuth status for {string} becomes {string}", async ({}, provider: string, status: string) => {
  setStubbedOAuthFlow(provider, status as "pending" | "ready" | "expired" | "denied")
})

When("I open the OAuth pairing for provider {string}", async ({ page }, provider: string) => {
  await page.getByTestId("oauth-device-open-" + provider).click()
  await expect(page.getByTestId("oauth-device-user-code")).toBeVisible()
})

Then("the pairing code {string} should be visible", async ({ page }, code: string) => {
  await expect(page.getByTestId("oauth-device-user-code")).toContainText(code)
})

Then("the pairing should close", async ({ page }) => {
  await expect(page.getByTestId("oauth-device-dialog")).toBeHidden({ timeout: 15_000 })
})

Then("the OAuth disconnect control should be visible", async ({ page }) => {
  await expect(page.getByTestId("oauth-device-disconnect")).toBeVisible()
})
