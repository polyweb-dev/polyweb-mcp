import { expect } from "@playwright/test"
import { Given, Then, When } from "./fixtures"
import { chooseOption } from "./providerConfigUi"

Given("Alpha has a Tavily pool for Search and Fetch", async ({ page }) => {
  await page.route(/\/api\/v1\/projects\/[^/]+\/providers$/, (route) =>
    route.fulfill({ json: { providers: ["tavily", "keenable"].map((provider) => ({
      provider_type: provider, capability: ["search", "fetch"], kill_switch: false,
      system_enabled_operations: ["search", "fetch"], effective_operations: ["search", "fetch"],
      call_cost_usd: { search: provider === "keenable" ? 0 : "0.008", fetch: 0 },
      keyless_call_cost_usd: provider === "keenable" ? { search: 0, fetch: 0 } : {},
      credentials: [], bindings: [],
    })) } }))
  await page.goto("/account/keys")
  await page.getByRole("button", { name: "Add key", exact: true }).first().click()
  const key = page.getByRole("dialog", { name: "Add key" })
  await chooseOption(key, "Provider", "Tavily")
  await key.getByLabel("Label", { exact: true }).fill("Alpha Tavily")
  await key.getByLabel("API key", { exact: true }).fill("fake-tavily-key")
  await key.getByRole("button", { name: "Add key", exact: true }).click()
  await expect(key).toBeHidden()
  await page.getByRole("row").filter({ hasText: "Alpha Tavily" }).getByRole("button", { name: "Create pool" }).click()
  const pool = page.getByRole("dialog", { name: "Create pool" })
  await chooseOption(pool, "Project", "Alpha")
  await pool.getByLabel("Pool name").fill("Alpha Tavily pool")
  await expect(pool.getByRole("checkbox", { name: "Search", exact: true })).toBeChecked()
  await expect(pool.getByRole("checkbox", { name: "Fetch", exact: true })).toBeChecked()
  await pool.getByRole("button", { name: "Create pool", exact: true }).click()
  await expect(pool).toBeHidden()
})

When("I move Keenable to the top of the Search order", async ({ page }) => {
  await page.getByRole("button", { name: "Move Keenable priority up" }).click()
  await expect(page.getByRole("table", { name: "Search provider order" }).locator("tbody tr").first()).toContainText("Keenable")
  await expect(page.getByRole("combobox", { name: "Order by" })).toContainText("Custom")
})

Then("the Fetch order remains unchanged", async ({ page }) => {
  await page.getByRole("tab", { name: /^Fetch/ }).click()
  await expect(page.getByRole("table", { name: "Fetch provider order" }).locator("tbody tr").first()).toContainText("Tavily")
})

When("I confirm stopping Tavily Search", async ({ page }) => {
  await page.getByRole("tab", { name: /^Search/ }).click()
  await page.getByRole("switch", { name: "Use Tavily for Search" }).click()
  const dialog = page.getByRole("dialog", { name: "Stop Tavily Search" })
  await expect(dialog).toContainText("Fetch stays on")
  await dialog.getByRole("button", { name: "Stop Search" }).click()
  await expect(dialog).toBeHidden()
})

When("I reload the Providers page", async ({ page }) => {
  await page.reload()
})

Then("Tavily serves Fetch but not Search", async ({ page }) => {
  const search = page.getByRole("table", { name: "Search provider order" })
  await expect(search.getByRole("row", { name: /Tavily/ })).toHaveCount(0)
  await page.getByRole("tab", { name: /^Fetch/ }).click()
  await expect(page.getByRole("table", { name: "Fetch provider order" }).getByRole("row", { name: /Tavily/ })).toBeVisible()
})
