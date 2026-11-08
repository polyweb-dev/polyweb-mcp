import { expect } from "@playwright/test"
import type { Page } from "@playwright/test"
import { Given, Then, When } from "./fixtures"
import { projectStubId } from "./projectStub"
import {
  OAUTH_USER_CODE,
  OAUTH_VERIFICATION_URI,
  approveOAuthDevice,
  denyOAuthDevice,
  oauthPollCount,
  oauthStatusOf,
  seedPrivateOAuthCredential,
  seedSystemOAuthCredential,
} from "./providerConfigStub"
import { confirmIfAsked, secretLeaks } from "./providerConfigUi"

/**
 * Credential-scoped Parallel OAuth device flow (U3 contract): the dialog
 * "Connect Parallel" shows the user code (data-testid oauth-user-code), an
 * "Open verification page" link and a status line; the stub answers device
 * with only user_code, verification_uri, interval 1 and expires_in, and polls
 * stay pending until the account approves or denies.
 */

function oauthDialog(page: Page) {
  return page.getByRole("dialog", { name: "Connect Parallel", exact: true })
}

Given(
  "project {word} has a private Parallel OAuth credential {string}",
  async ({}, projectName: string, label: string) => {
    seedPrivateOAuthCredential(projectStubId(projectName), label)
  }
)

Given("the system has a Parallel OAuth credential {string}", async ({}, label: string) => {
  seedSystemOAuthCredential(label)
})

When("I connect the credential {string}", async ({ page }, label: string) => {
  await page.getByRole("button", { name: `Actions for ${label}`, exact: true }).click({ timeout: 15_000 })
  await page.getByRole("button", { name: "Connect", exact: true }).click()
  await expect(oauthDialog(page)).toBeVisible()
})

Then("the OAuth dialog shows only the user code and the verification link", async ({ page }) => {
  const dialog = oauthDialog(page)
  await expect(dialog.getByTestId("oauth-user-code")).toHaveText(OAUTH_USER_CODE)
  const link = dialog.getByRole("link", { name: "Open verification page", exact: true })
  await expect(link).toHaveAttribute("href", OAUTH_VERIFICATION_URI)
  await expect(link).toHaveAttribute("target", "_blank")
  const rel = (await link.getAttribute("rel")) ?? ""
  expect(rel.split(/\s+/)).toEqual(expect.arrayContaining(["noopener", "noreferrer"]))
  // The verification link is the only link: no prefilled "complete" URL.
  await expect(dialog.getByRole("link")).toHaveCount(1)
})

Then("the OAuth dialog status reads {string}", async ({ page }, status: string) => {
  await expect(oauthDialog(page)).toContainText(status, { timeout: 15_000 })
})

When("the Parallel account approves the device for {string}", async ({}, label: string) => {
  approveOAuthDevice(label)
})

When("the Parallel account denies the device for {string}", async ({}, label: string) => {
  denyOAuthDevice(label)
})

Then("the OAuth state of {string} is {string}", async ({}, label: string, status: string) => {
  await expect.poll(() => oauthStatusOf(label)).toBe(status)
})

Then("the OAuth user code is in neither browser storage nor the URL", async ({ page }) => {
  const leaks = (await secretLeaks(page, OAUTH_USER_CODE)).filter((hit) => hit !== "dom")
  expect(leaks).toEqual([])
})

Then("the device flow of {string} is being polled", async ({}, label: string) => {
  await expect.poll(() => oauthPollCount(label), { timeout: 10_000 }).toBeGreaterThan(0)
})

Then("polling for {string} has stopped", async ({ page }, label: string) => {
  await expect.poll(() => oauthPollCount(label)).toBeGreaterThan(0)
  const settled = oauthPollCount(label)
  // The server interval is 1 second: three intervals without a poll prove the
  // loop ended. A bounded wait is the only way to observe an absence of calls.
  await page.waitForTimeout(3_200)
  expect(oauthPollCount(label)).toBe(settled)
})

When("I close the OAuth dialog", async ({ page }) => {
  await page.keyboard.press("Escape")
  await expect(oauthDialog(page)).toHaveCount(0)
})

When("I close the open dialog", async ({ page }) => {
  await expect(page.getByRole("dialog")).toHaveCount(1)
  await page.keyboard.press("Escape")
  await expect(page.getByRole("dialog")).toHaveCount(0)
})

When("I disconnect the credential {string}", async ({ page }, label: string) => {
  await page.getByRole("button", { name: `Actions for ${label}`, exact: true }).click({ timeout: 15_000 })
  await page.getByRole("button", { name: "Disconnect", exact: true }).click()
  await confirmIfAsked(page, "Disconnect")
})

Then("the credential {string} offers {string}", async ({ page }, label: string, item: string) => {
  await page.getByRole("button", { name: `Actions for ${label}`, exact: true }).click({ timeout: 15_000 })
  await expect(page.getByRole("button", { name: item, exact: true })).toBeVisible({ timeout: 15_000 })
  await page.keyboard.press("Escape")
})
