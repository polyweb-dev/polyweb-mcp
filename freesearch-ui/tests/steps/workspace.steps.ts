import { expect } from "@playwright/test"
import { Given, When, Then } from "./fixtures"

Given("I navigate to the web application", async ({ page }) => {
  await page.goto("/")
  await expect(page.getByText("FreeSearch", { exact: true })).toBeVisible()
})

When("I select the {string} header tab", async ({ page }, tabLabel: string) => {
  await page.getByRole("button", { name: tabLabel, exact: true }).click()
})

Then("I should see the {string} heading", async ({ page }, heading: string) => {
  await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible()
})
