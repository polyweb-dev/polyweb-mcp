import { expect } from "@playwright/test"
import { When, Then } from "./fixtures"

/**
 * P1-FINAL Providers-into-Settings merge — history + merged-table steps.
 *
 * Step-text uniqueness: none of these patterns exist in workspace.steps.ts,
 * routing.steps.ts, tab-unification.steps.ts, settings.steps.ts,
 * activity.steps.ts, playground.steps.ts, theme.steps.ts, visual.steps.ts,
 * or url-routing.steps.ts.
 */

Then(
  "the sidebar should not expose a {string} link",
  async ({ page }, label: string) => {
    await expect(
      page.getByRole("link", { name: label, exact: true })
    ).toHaveCount(0)
  }
)

Then(
  "the merged provider table should expose headers {string}",
  async ({ page }, csv: string) => {
    const expected = csv.split(",").map((h) => h.trim())
    const table = page.getByRole("table").first()
    await expect(table).toBeVisible()
    const headers = table.locator("thead th")
    await expect(headers).toHaveCount(expected.length)
    for (let index = 0; index < expected.length; index += 1) {
      await expect(headers.nth(index)).toHaveText(expected[index])
    }
  }
)

Then(
  "the merged provider table should show the {string} endpoint",
  async ({ page }, endpoint: string) => {
    const table = page.getByRole("table").first()
    await expect(table.getByText(endpoint, { exact: false }).first()).toBeVisible()
  }
)

Then(
  "the merged provider table should show a {string} breaker action",
  async ({ page }, label: string) => {
    const table = page.getByRole("table").first()
    await expect(
      table.getByRole("button", { name: label, exact: true }).first()
    ).toBeVisible()
  }
)

Then("the page should not contain {string}", async ({ page }, text: string) => {
  await expect(page.locator("body")).not.toContainText(text)
})

When(
  "I open the connection test for {string}",
  async ({ page }, provider: string) => {
    const row = page
      .getByText(provider, { exact: true })
      .first()
      .locator("xpath=ancestor::tr[1]")
    await row.getByRole("button", { name: new RegExp(`${escapeRegExp(provider)}.*test`, "i") }).click()
  }
)

Then(
  "I should see the connection test dialog for {string}",
  async ({ page }, provider: string) => {
    const dialog = page.getByRole("dialog")
    await expect(dialog).toBeVisible()
    await expect(dialog).toContainText(provider)
  }
)

Then("the connection test dialog should show an endpoint", async ({ page }) => {
  const dialog = page.getByRole("dialog")
  await expect(dialog).toBeVisible()
  await expect(dialog).toContainText(/api\./)
})

When("I dismiss the dialog with Escape", async ({ page }) => {
  await page.keyboard.press("Escape")
})

Then("the connection test dialog should be closed", async ({ page }) => {
  await expect(page.getByRole("dialog")).toHaveCount(0)
})

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}
