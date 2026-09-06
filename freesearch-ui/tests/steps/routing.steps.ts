import { expect } from "@playwright/test"
import type { Page } from "@playwright/test"
import { Given, When, Then } from "./fixtures"

Given("I am on the Routing view", async ({ page }) => {
  await page.getByRole("button", { name: "Routing", exact: true }).click()
  await expect(page.getByRole("heading", { name: "Routing", exact: true })).toBeVisible()
})

Then(
  "the routing sub-tabs should be visible: {string}, {string}, {string}, and {string}",
  async ({ page }, first: string, second: string, third: string, fourth: string) => {
    for (const label of [first, second, third, fourth]) {
      await expect(page.getByRole("tab", { name: label, exact: true })).toHaveCount(1)
    }
  }
)

When("I choose the {string} routing strategy", async ({ page }, strategy: string) => {
  await page.getByRole("tab", { name: "Strategy", exact: true }).click()
  await page.getByRole("button", { name: new RegExp(`^${escapeRegExp(strategy)}`) }).click()
})

Then("{string} is the primary routing provider", async ({ page }, provider: string) => {
  const providerText = page.getByText(provider, { exact: true }).first()
  await expect(providerText).toBeVisible()

  // The provider card and its Primary marker are one accessible region.
  const primaryRegion = providerText.locator(
    "xpath=ancestor::*[contains(normalize-space(.), 'Primary')][1]"
  )
  await expect(primaryRegion).toContainText(provider)
  await expect(primaryRegion).toContainText("Primary")
})

Then("the routing status should show {string}", async ({ page }, status: string) => {
  await expect(page.getByText(status, { exact: true })).toBeVisible()
})

Then("the routing status should not use a middle-dot separator", async ({ page }) => {
  const activeStatus = page.getByText("Failover active", { exact: true })
  const statusRegion = activeStatus.locator("xpath=../..")
  await expect(statusRegion).not.toContainText("·")
})

When("I open the {string} routing tab", async ({ page }, tabLabel: string) => {
  await page.getByRole("tab", { name: tabLabel, exact: true }).click()
})

When("I enter the simulated search query {string}", async ({ page }, query: string) => {
  await page.getByPlaceholder("Type simulated query...", { exact: true }).fill(query)
})

When("I choose the {string} simulator operation", async ({ page }, operation: string) => {
  await page.getByRole("button", { name: operation, exact: true }).click()
})

Then("the simulator input placeholder should be {string}", async ({ page }, placeholder: string) => {
  await expect(page.getByPlaceholder(placeholder, { exact: true })).toBeVisible()
})

When("I click the {string} button", async ({ page }, buttonLabel: string) => {
  await page.getByRole("button", { name: buttonLabel, exact: true }).click()
})

Then("the execution pipeline should contain the {string} step", async ({ page }, step: string) => {
  await expect(page.getByText(step, { exact: true })).toBeVisible()
})

Then(
  "the execution pipeline should contain the primary provider {string}",
  async ({ page }, provider: string) => {
    await expect(page.getByText(provider, { exact: true }).first()).toBeVisible()
  }
)

Then("the failover cascade should be rendered", async ({ page }) => {
  await expect(page.getByText(/Failover cascade/i).first()).toBeVisible()
})

When("I choose the {string} ranks operation", async ({ page }, operation: string) => {
  const button = page.getByRole("button", { name: operation, exact: true }).last()
  if (await button.count()) {
    await button.click()
    return
  }

  await page.getByRole("tab", { name: operation, exact: true }).click()
})

When("I filter the ranks by provider text {string}", async ({ page }, filterText: string) => {
  const filter = page.getByRole("textbox").last()
  await filter.fill(filterText)
})

Then("the ranks table should contain exactly {int} provider rows", async ({ page }, count: number) => {
  const table = page.getByRole("table")
  await expect(table).toBeVisible()
  await expect(table.getByRole("row")).toHaveCount(count + 1)
})

Then(
  "the ranks row for {string} should show rank {string} and role {string}",
  async ({ page }, provider: string, rank: string, role: string) => {
    await expectRankRow(page, provider, rank, role)
  }
)

Then(
  "the filtered ranks row for {string} should show rank {string} and role {string}",
  async ({ page }, provider: string, rank: string, role: string) => {
    await expectRankRow(page, provider, rank, role)
  }
)

async function expectRankRow(page: Page, provider: string, rank: string, role: string) {
  const table = page.getByRole("table")
  const row = table
    .getByRole("row")
    .filter({ hasText: provider })
    .filter({ hasText: rank })
    .filter({ hasText: role })
  await expect(row).toHaveCount(1)
  await expect(row.getByText(rank, { exact: true })).toBeVisible()
  await expect(row.getByText(provider, { exact: true })).toBeVisible()
  await expect(row.getByText(role, { exact: true })).toBeVisible()
}

When("I open the {string} resilience tab", async ({ page }, tabLabel: string) => {
  await page.getByRole("tab", { name: tabLabel, exact: true }).click()
})

Then("the resilience row {string} should be visible", async ({ page }, label: string) => {
  await expect(page.getByText(label, { exact: true })).toBeVisible()
})

Then(
  "the resilience row {string} should show {string}",
  async ({ page }, label: string, value: string) => {
    const row = page.getByText(label, { exact: true }).locator("xpath=..")
    await expect(row).toContainText(value)
  }
)

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}
