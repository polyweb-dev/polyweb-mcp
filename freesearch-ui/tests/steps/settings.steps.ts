import { expect } from "@playwright/test"
import type { Page } from "@playwright/test"
import { Given, When, Then } from "./fixtures"

Given("I am on the Settings view", async ({ page }) => {
  await page.getByRole("button", { name: "Settings", exact: true }).click()
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

When(
  "I turn the {string} {string} operation off",
  async ({ page }, provider: string, operation: string) => {
    await getSegmentButton(page, provider, operation, "Off").click()
  }
)

Then(
  "the {string} {string} operation should be off",
  async ({ page }, provider: string, operation: string) => {
    await expect(getSegmentButton(page, provider, operation, "Off")).toHaveAttribute(
      "aria-pressed",
      "true"
    )
  }
)

Then(
  "the {string} {string} operation should remain off",
  async ({ page }, provider: string, operation: string) => {
    await expect(getSegmentButton(page, provider, operation, "Off")).toHaveAttribute(
      "aria-pressed",
      "true"
    )
  }
)

Then("the keys tab should show a masked fingerprint containing bullets", async ({ page }) => {
  await expect(page.locator("body")).toContainText("••••••••")
})

Then(
  "the keys tab should not contain {string}, {string}, {string}, or {string}",
  async ({ page }, first: string, second: string, third: string, fourth: string) => {
    const body = await page.locator("body").innerText()
    for (const forbidden of [first, second, third, fourth]) {
      expect(body).not.toContain(forbidden)
    }
  }
)

When(
  "I save the key {string} for {string}",
  async ({ page }, rawKey: string, provider: string) => {
    const card = getKeyCard(page, provider)
    await card.locator('input[type="password"]').fill(rawKey)
    await card.getByRole("button", { name: "Save", exact: true }).click()
  }
)

Then("the {string} key status should be {string}", async ({ page }, provider: string, status: string) => {
  await expect(getKeyCard(page, provider).getByText(status, { exact: true })).toBeVisible()
})

Then(
  "the {string} key fingerprint should be {string}",
  async ({ page }, provider: string, fingerprint: string) => {
    await expect(getKeyCard(page, provider).getByText(fingerprint, { exact: true })).toBeVisible()
  }
)

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
  return page
    .getByText(provider, { exact: true })
    .first()
    .locator("xpath=ancestor::*[.//*[normalize-space()='Global']][1]")
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

function getKeyCard(page: Page, provider: string) {
  return page
    .getByText(provider, { exact: true })
    .first()
    .locator("xpath=ancestor::*[.//input and .//button[normalize-space()='Save']][1]")
}
