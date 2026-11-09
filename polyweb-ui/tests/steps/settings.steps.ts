import { expect } from "@playwright/test"
import type { Page } from "@playwright/test"
import { Given, When, Then } from "./fixtures"

Given("I am on the Settings view", async ({ page }) => {
  await page.getByRole("link", { name: "Providers", exact: true }).click()
  await expect(page.getByRole("heading", { name: "Providers", exact: true })).toBeVisible()
})

When("I view the provider catalog", async ({ page }) => {
  await expect(page.getByRole("heading", { name: "Providers", exact: true })).toBeVisible()
})

Then("the settings page should expose exactly {int} sub-tabs", async ({ page }, count: number) => {
  await expect(page.getByRole("tab")).toHaveCount(count)
})

Then("the settings page should not expose a {string} tab", async ({ page }, tabLabel: string) => {
  await expect(page.getByRole("tab", { name: tabLabel, exact: true })).toHaveCount(0)
})

Then("the settings page should not expose an {string} button", async ({ page }, buttonLabel: string) => {
  await expect(page.getByRole("button", { name: buttonLabel, exact: true })).toHaveCount(0)
})

Then("the provider catalog has no order controls", async ({ page }) => {
  const table = page.getByRole("table").first()
  await expect(table.getByRole("columnheader", { name: "Cost per call" })).toBeVisible()
  await expect(table.getByRole("columnheader", { name: /priority|rank/i })).toHaveCount(0)
  await expect(table.getByRole("button", { name: /priority (up|down)/i })).toHaveCount(0)
  await expect(table.locator("[draggable=true]")).toHaveCount(0)
})

When(
  "I turn the {string} {string} operation off",
  async ({ page }, provider: string, operation: string) => {
    const sw = page.getByRole("switch", {
      name: new RegExp(`${escapeRegExp(provider)} ${escapeRegExp(operation)} routing`, "i"),
    })
    if (await sw.count()) {
      if ((await sw.getAttribute("aria-checked")) === "true") {
        await sw.click()
      }
      return
    }
    await getSegmentButton(page, provider, operation, "Off").click()
  }
)

Then(
  "the {string} {string} operation should be off",
  async ({ page }, provider: string, operation: string) => {
    const sw = page.getByRole("switch", {
      name: new RegExp(`${escapeRegExp(provider)} ${escapeRegExp(operation)} routing`, "i"),
    })
    if (await sw.count()) {
      await expect(sw).toHaveAttribute("aria-checked", "false")
      return
    }
    await expect(getSegmentButton(page, provider, operation, "Off")).toHaveAttribute(
      "aria-pressed",
      "true"
    )
  }
)

Then(
  "the {string} {string} operation should remain off",
  async ({ page }, provider: string, operation: string) => {
    const sw = page.getByRole("switch", {
      name: new RegExp(`${escapeRegExp(provider)} ${escapeRegExp(operation)} routing`, "i"),
    })
    if (await sw.count()) {
      await expect(sw).toHaveAttribute("aria-checked", "false")
      return
    }
    await expect(getSegmentButton(page, provider, operation, "Off")).toHaveAttribute(
      "aria-pressed",
      "true"
    )
  }
)

Then("the settings page should expose no secret input", async ({ page }) => {
  // Provider secrets moved to credential instances (U3): the global page
  // never renders a write-only secret input.
  await expect(page.getByRole("table").first()).toBeVisible()
  await expect(page.locator('input[type="password"]')).toHaveCount(0)
})

Then("the failover switch {string} should be visible", async ({ page }, label: string) => {
  await expect(page.getByText(label, { exact: true })).toBeVisible()
})

Then("the failover row {string} should be visible", async ({ page }, label: string) => {
  await expect(page.getByText(label, { exact: true })).toBeVisible()
})

Then("the failover tab should not show the removed per-condition switches", async ({ page }) => {
  for (const removed of [
    "Fallback chaining",
    "Failover on rate limit (429)",
    "Failover on timeout",
    "Failover on server error (5xx)",
    "Cascade depth",
    "Timeout budget",
  ]) {
    await expect(page.getByText(removed, { exact: true })).toHaveCount(0)
  }
  await expect(page.locator("main")).not.toContainText(/session-only|not enforced|not exposed/i)
})

function getProviderRow(page: Page, provider: string) {
  const cell = page.getByText(provider, { exact: true }).first()
  return cell.locator("xpath=ancestor-or-self::tr | ancestor::*[.//*[normalize-space()='Enabled']][1]").first()
}

function getSegmentButton(
  page: Page,
  provider: string,
  operation: string,
  value: "On" | "Off"
) {
  const row = getProviderRow(page, provider)
  const operationLabel = row.getByText(operation, { exact: true })
  return operationLabel.locator("xpath=..").getByRole("button", { name: value, exact: true })
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}
