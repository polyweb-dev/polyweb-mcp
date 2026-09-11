import { expect } from "@playwright/test"
import { Given, When, Then } from "./fixtures"
import {
  setDashboardQuotaOverride,
  parallelPairedQuota,
  setStubbedOAuthFlow,
  failStubbedOAuthBegin,
} from "./backendStub"

/**
 * Parallel OAuth device pairing (parallel-oauth-pairing.feature @oauth).
 *
 * The stubbed backend serves POST/GET/DELETE
 * /api/v1/providers/{id}/oauth[/device-code|/status] from per-scenario
 * in-memory flow state (see backendStub.ts): unpaired by default (GET status
 * 404s), mutable via the Given/When steps below so polling picks up state
 * transitions without sleeps. All selectors use the frozen
 * data-testid="oauth-device-*" convention; auto-waiting assertions only.
 */

// F-TESTID-01 RESOLVED: the row connect button is oauth-device-open-*.
const OPEN_PREFIX = "oauth-device-open-"
const DISCONNECT_ID = "oauth-device-disconnect"
const DISCONNECT_CONFIRM_ID = "oauth-device-confirm-disconnect"

Given("the stubbed OAuth flow for {string} is unpaired", async ({}, provider: string) => {
  setStubbedOAuthFlow(provider, "unpaired")
})

Given(
  "the stubbed OAuth flow for {string} is {string}",
  async ({}, provider: string, status: string) => {
    setStubbedOAuthFlow(provider, status as "pending" | "ready" | "expired" | "denied")
  }
)

Given(
  "the stubbed OAuth device-code request for {string} fails",
  async ({}, provider: string) => {
    failStubbedOAuthBegin(provider)
  }
)

When(
  "I start OAuth pairing for provider {string}",
  async ({ page }, provider: string) => {
    // Shipped connect id is oauth-connect-* (F-TESTID-01: must become oauth-device-*).
    await page.getByTestId(OPEN_PREFIX + provider).click()
    await expect(page.getByTestId("oauth-device-user-code")).toBeVisible()
  }
)

When(
  "the stubbed OAuth flow for {string} becomes {string}",
  async ({}, provider: string, status: string) => {
    setStubbedOAuthFlow(provider, status as "pending" | "ready" | "expired" | "denied")
  }
)

// Error-path begin: stubbed 503 renders alert with no code and no polling
// (see parallelOAuthPairing.test.tsx begin-failure case). Do not reuse the
// shared start step here; it asserts the user-code element.
When(
  "I attempt OAuth pairing for provider {string} with a failing begin",
  async ({ page }, provider: string) => {
    await page.getByTestId(OPEN_PREFIX + provider).click()
    await expect(page.getByTestId("oauth-device-error")).toBeVisible()
    await expect(page.getByTestId("oauth-device-error")).toContainText(/oauth unavailable/i)
    await expect(page.getByTestId("oauth-device-user-code")).toHaveCount(0)
  }
)

When(
  "the stubbed backend pairs {string} with balance {string}",
  async ({}, provider: string, _balance: string) => {
    // Dashboard FIRST, then ready: the SUT's post-ready dashboard refresh
    // must already see the authoritative row (no request race).
    setDashboardQuotaOverride(parallelPairedQuota())
    setStubbedOAuthFlow(provider, "ready")
  }
)

When("I retry OAuth pairing", async ({ page }) => {
  await page.getByTestId("oauth-device-retry").click()
  await expect(page.getByTestId("oauth-device-user-code")).toBeVisible()
})

When(
  "I disconnect OAuth pairing for provider {string}",
  // Single-row suffixless testids; the name documents intent.
  async ({ page }, _provider: string) => {
    await page.getByTestId(DISCONNECT_ID).click()
    const confirm = page.getByTestId(DISCONNECT_CONFIRM_ID)
    if (await confirm.isVisible().catch(() => false)) {
      await confirm.click()
    }
  }
)

Then("the OAuth pairing dialog should show the user code", async ({ page }) => {
  const code = page.getByTestId("oauth-device-user-code")
  await expect(code).toBeVisible()
  await expect(code).not.toBeEmpty()
})

Then("the OAuth pairing dialog should link to the verification URL", async ({ page }) => {
  const link = page.getByTestId("oauth-device-open-verification")
  await expect(link).toBeVisible()
  await expect(link).toHaveAttribute("href", /https:\/\//)
})

Then("the OAuth pairing dialog should close automatically", async ({ page }) => {
  // The shipped dialog root carries no testid: select by dialog role.
  await expect(page.getByRole("dialog")).toBeHidden({ timeout: 15_000 })
})

Then("the OAuth pairing should show an error", async ({ page }) => {
  await expect(page.getByTestId("oauth-device-error")).toBeVisible()
})

Then("I should be able to retry OAuth pairing", async ({ page }) => {
  await expect(page.getByTestId("oauth-device-retry")).toBeEnabled()
})
