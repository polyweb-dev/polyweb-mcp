import { expect } from "@playwright/test"
import type { Page } from "@playwright/test"
import { Given, When, Then } from "./fixtures"
import { delayStubbedProviderPatch, failStubbedProviderPatch } from "./backendStub"

/**
 * Provider access flags (PLAN §9 UI BDD).
 *
 * Semantic switch labels only: operation switches expose
 * "{Provider} {search|fetch} routing", the global switch exposes
 * "{Provider} global routing", and unsupported tools show a dash with
 * "{Provider} does not support {operation}" for assistive technology.
 *
 * Step-text uniqueness: every pattern contains "access flag",
 * "operation picker should exclude", or "ranks table should exclude",
 * none of which exist in any other steps file.
 */

function operationSwitch(page: Page, provider: string, operation: string) {
  return page.getByRole("switch", {
    name: `${provider} ${operation.toLowerCase()} routing`,
    exact: true,
  })
}

function globalSwitch(page: Page, provider: string) {
  return page.getByRole("switch", {
    name: `${provider} global routing`,
    exact: true,
  })
}

function toStubBackendId(display: string): string {
  if (display === "Brave Search") return "brave"
  if (display === "You.com") return "you"
  return display.toLowerCase()
}

Given(
  "the provider PATCH for {string} will fail with {string}",
  async ({ page }, provider: string, message: string) => {
    void page
    failStubbedProviderPatch(toStubBackendId(provider), message)
  }
)

Given(
  "the provider PATCH for {string} is delayed by {int} milliseconds",
  async ({ page }, provider: string, ms: number) => {
    void page
    delayStubbedProviderPatch(toStubBackendId(provider), ms)
  }
)

When(
  "I set the {string} {string} access flag off",
  async ({ page }, provider: string, operation: string) => {
    const sw = operationSwitch(page, provider, operation)
    await expect(sw).toBeVisible()
    const checked = await sw.getAttribute("aria-checked")
    if (checked !== "false") {
      await sw.click()
    }
  }
)

When(
  "I set the {string} {string} access flag on",
  async ({ page }, provider: string, operation: string) => {
    const sw = operationSwitch(page, provider, operation)
    await expect(sw).toBeVisible()
    const checked = await sw.getAttribute("aria-checked")
    if (checked !== "true") {
      await sw.click()
    }
  }
)

When(
  "I set the {string} global access flag off",
  async ({ page }, provider: string) => {
    const sw = globalSwitch(page, provider)
    await expect(sw).toBeVisible()
    const checked = await sw.getAttribute("aria-checked")
    if (checked !== "false") {
      await sw.click()
    }
  }
)

When(
  "I set the {string} global access flag on",
  async ({ page }, provider: string) => {
    const sw = globalSwitch(page, provider)
    await expect(sw).toBeVisible()
    const checked = await sw.getAttribute("aria-checked")
    if (checked !== "true") {
      await sw.click()
    }
  }
)

When(
  "I start to set the {string} {string} access flag off without waiting",
  async ({ page }, provider: string, operation: string) => {
    const sw = operationSwitch(page, provider, operation)
    await expect(sw).toBeVisible()
    await expect(sw).toBeEnabled()
    await sw.click()
  }
)

Then(
  "the {string} {string} access flag should be off",
  async ({ page }, provider: string, operation: string) => {
    await expect(operationSwitch(page, provider, operation)).toHaveAttribute(
      "aria-checked",
      "false"
    )
  }
)

Then(
  "the {string} {string} access flag should be on",
  async ({ page }, provider: string, operation: string) => {
    await expect(operationSwitch(page, provider, operation)).toHaveAttribute(
      "aria-checked",
      "true"
    )
  }
)

Then(
  "the {string} global access flag should be off",
  async ({ page }, provider: string) => {
    await expect(globalSwitch(page, provider)).toHaveAttribute("aria-checked", "false")
  }
)

Then(
  "the {string} global access flag should be on",
  async ({ page }, provider: string) => {
    await expect(globalSwitch(page, provider)).toHaveAttribute("aria-checked", "true")
  }
)

Then(
  "the {string} {string} access flag should be disabled while pending",
  async ({ page }, provider: string, operation: string) => {
    await expect(operationSwitch(page, provider, operation)).toBeDisabled()
  }
)

Then(
  "the {string} global access flag should be disabled while pending",
  async ({ page }, provider: string) => {
    await expect(globalSwitch(page, provider)).toBeDisabled()
  }
)

Then(
  "the {string} {string} access flag should be off and locked as unsupported",
  async ({ page }, provider: string, operation: string) => {
    const unsupported = page.getByText(`${provider} does not support ${operation.toLowerCase()}`, { exact: true })
    const cell = unsupported.locator("xpath=ancestor::td[1]")
    await expect(cell).toContainText("—")
    await expect(cell.getByRole("switch")).toHaveCount(0)
    await unsupported.locator("..").hover()
    await expect(page.getByRole("tooltip", { name: "Not supported", exact: true })).toBeVisible()
  }
)

Then(
  "the {string} {string} access flag should be disabled while preserving {string}",
  async ({ page }, provider: string, operation: string, preserved: string) => {
    const sw = operationSwitch(page, provider, operation)
    await expect(sw).toBeDisabled()
    await expect(sw).toHaveAttribute(
      "aria-checked",
      preserved === "on" ? "true" : "false"
    )
  }
)

Then(
  "the {string} operation picker should exclude {string}",
  async ({ page }, operation: string, provider: string) => {
    const select = page.getByTestId(`playground-${operation.toLowerCase()}-provider`)
    await expect(select).toBeVisible()
    await select.click()
    const options = page.getByRole("listbox").getByRole("option")
    await expect(options.first()).toBeAttached()
    const labels = await options.allTextContents()
    expect(labels).not.toContain(provider)
    await page.keyboard.press("Escape")
  }
)

Then(
  "the {string} ranks table should exclude {string}",
  async ({ page }, _operation: string, provider: string) => {
    const table = page.getByRole("table")
    await expect(table).toBeVisible()
    await expect(table.getByRole("row").filter({ hasText: provider })).toHaveCount(0)
  }
)
