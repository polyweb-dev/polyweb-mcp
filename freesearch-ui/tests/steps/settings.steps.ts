import { expect } from "@playwright/test"
import type { Page } from "@playwright/test"
import { Given, When, Then } from "./fixtures"

Given("I am on the Settings view", async ({ page }) => {
  await page.getByRole("link", { name: "Settings", exact: true }).click()
  await expect(page.getByRole("heading", { name: "Settings", exact: true })).toBeVisible()
})

When("I open the {string} settings tab", async ({ page }, tabLabel: string) => {
  await page.getByRole("tab", { name: tabLabel, exact: true }).click()
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

Then(
  "the {string} upward priority arrow should be disabled",
  async ({ page }, provider: string) => {
    await expect(getProviderRow(page, provider).getByRole("button", { name: /up/i })).toBeDisabled()
  }
)

Then(
  "the {string} downward priority arrow should be disabled",
  async ({ page }, provider: string) => {
    await expect(getProviderRow(page, provider).getByRole("button", { name: /down/i })).toBeDisabled()
  }
)

Then("the first provider row upward priority arrow should be disabled", async ({ page }) => {
  // Boundary-agnostic: live registries may reorder (equal priorities sort by
  // provider_id), so the boundary is the first RENDERED row, not a fixed name.
  const upButtons = page.getByRole("button", { name: /priority up/i })
  await expect(upButtons.first()).toBeDisabled()
})

Then("the last provider row downward priority arrow should be disabled", async ({ page }) => {
  const downButtons = page.getByRole("button", { name: /priority down/i })
  await expect(downButtons.last()).toBeDisabled()
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
  await expect(page.getByRole("tab").first()).toBeVisible()
  await expect(page.locator('input[type="password"]')).toHaveCount(0)
})

Then("the failover switch {string} should be visible", async ({ page }, label: string) => {
  await expect(page.getByText(label, { exact: true })).toBeVisible()
})

Then("each failover switch should expose a description", async ({ page }) => {
  const labels = [
    "Fallback chaining",
    "Failover on rate limit (429)",
    "Failover on timeout",
    "Failover on server error (5xx)",
  ]

  for (const label of labels) {
    const labelNode = page.getByText(label, { exact: true })
    await expect(labelNode).toBeVisible()
    const labelParent = labelNode.locator("xpath=..")
    const textElements = labelParent.locator("span, p").filter({ hasText: /\S/ })
    expect(await textElements.count()).toBeGreaterThan(1)
  }
})

Then("the failover operation switches should be vertically stacked", async ({ page }) => {
  const labels = [
    "Failover on rate limit (429)",
    "Failover on timeout",
    "Failover on server error (5xx)",
  ]
  const boxes = await Promise.all(
    labels.map(async (label) => page.getByText(label, { exact: true }).boundingBox())
  )

  expect(boxes.every((box): box is NonNullable<typeof box> => box !== null)).toBe(true)
  for (let index = 1; index < boxes.length; index += 1) {
    expect(boxes[index]!.y).toBeGreaterThan(boxes[index - 1]!.y)
  }
})

Then("the failover row {string} should be visible", async ({ page }, label: string) => {
  await expect(page.getByText(label, { exact: true })).toBeVisible()
})

function getProviderRow(page: Page, provider: string) {
  const cell = page.getByText(provider, { exact: true }).first()
  return cell.locator("xpath=ancestor-or-self::tr | ancestor::*[.//*[normalize-space()='Global']][1]").first()
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
