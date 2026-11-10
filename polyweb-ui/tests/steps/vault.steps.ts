import { expect } from "@playwright/test"
import type { Locator, Page } from "@playwright/test"
import { Given, Then, When } from "./fixtures"
import { chooseOption, consoleCarrying, requestsCarrying, secretLeaks } from "./providerConfigUi"
import { approveVaultOAuth, seedVaultBalance } from "./vaultStub"

When("I open Keys and pools", async ({ page }) => {
  await page.goto("/account/keys")
  await expect(page.getByRole("heading", { name: "Keys and pools" })).toBeVisible()
})

When("I add a Brave Search vault key labelled {string} with a fake secret", async ({ page }, label: string) => {
  await page.goto("/account/keys")
  await expect(page.getByRole("heading", { name: "Keys and pools" })).toBeVisible()
  await page.getByRole("button", { name: "Add key", exact: true }).first().click()
  const dialog = page.getByRole("dialog", { name: "Add key" })
  await chooseOption(dialog, "Provider", "Brave Search")
  await dialog.getByLabel("Label", { exact: true }).fill(label)
  await dialog.getByLabel("API key", { exact: true }).fill("fake-brave-api-key")
  await dialog.getByRole("button", { name: "Add key", exact: true }).click()
  await expect(dialog).toBeHidden()
  await expect(page.getByRole("row").filter({ hasText: label })).toBeVisible()
})

/** Label of the most recently created pool (create-mode has no Pool name field; the label defaults to the project name). */
let createdPoolLabel = ""
/** Key label owning the most recently created pool (for expanding its pools table). */
let createdPoolKeyLabel = ""

/** Actual label of the last pool created through the shared pool helper. */
export function lastCreatedPoolLabel(): string {
  return createdPoolLabel
}

/** Key label of the last pool created through the shared pool helper. */
export function lastCreatedPoolKeyLabel(): string {
  return createdPoolKeyLabel
}

/** Create pool is an action in the key's portaled popup, not an inline row button. */
export async function openVaultPoolDialog(page: Page, keyLabel: string): Promise<Locator> {
  await page.goto("/account/keys")
  await expect(page.getByRole("heading", { name: "Keys and pools" })).toBeVisible()
  await page.getByRole("button", { name: `Actions for ${keyLabel}`, exact: true }).click()
  await page.locator('[data-slot="popover-content"]').getByRole("button", { name: "Create pool", exact: true }).click()
  const dialog = page.getByRole("dialog", { name: "Create pool" })
  await expect(dialog).toBeVisible()
  return dialog
}

When("I create a Search pool {string} for project Alpha on key {string}", async ({ page }, pool: string, key: string) => {
  const dialog = await openVaultPoolDialog(page, key)
  await chooseOption(dialog, "Project", "Alpha")
  // Create-mode renders no Pool name field (label defaults to the project
  // name); fill it only when present and record the actual created label.
  createdPoolLabel = "Alpha"
  createdPoolKeyLabel = key
  const nameField = dialog.getByLabel("Pool name")
  if ((await nameField.count()) > 0) {
    await nameField.fill(pool)
    createdPoolLabel = pool
  }
  await expect(dialog.getByRole("checkbox", { name: "Search", exact: true })).toBeChecked()
  const created = page.waitForResponse((response) => response.request().method() === "POST" &&
    /^\/api\/v1\/account\/vault\/keys\/[^/]+\/pools$/.test(new URL(response.url()).pathname))
  await dialog.getByRole("button", { name: "Create pool", exact: true }).click()
  const response = await created
  expect(response.ok()).toBe(true)
  createdPoolLabel = (await response.json()).label
  await expect(dialog).toBeHidden()
  await expect(page.getByRole("row").filter({ hasText: key })).toBeVisible()
})

When("I create a Search pool for project Alpha on key {string}", async ({ page }, key: string) => {
  const dialog = await openVaultPoolDialog(page, key)
  await chooseOption(dialog, "Project", "Alpha")
  createdPoolLabel = "Alpha"
  createdPoolKeyLabel = key
  const nameField = dialog.getByLabel("Pool name")
  if ((await nameField.count()) > 0) {
    await nameField.fill("Alpha Search")
    createdPoolLabel = "Alpha Search"
  }
  await expect(dialog.getByRole("checkbox", { name: "Search", exact: true })).toBeChecked()
  const created = page.waitForResponse((response) => response.request().method() === "POST" &&
    /^\/api\/v1\/account\/vault\/keys\/[^/]+\/pools$/.test(new URL(response.url()).pathname))
  await dialog.getByRole("button", { name: "Create pool", exact: true }).click()
  const response = await created
  expect(response.ok()).toBe(true)
  createdPoolLabel = (await response.json()).label
  await expect(dialog).toBeHidden()
  await expect(page.getByRole("row").filter({ hasText: key })).toBeVisible()
})

Then("the Search provider order shows {string} for {string}", async ({ page }, pool: string, provider: string) => {
  const row = page.getByRole("table", { name: "Search provider order" }).getByRole("row").filter({ hasText: provider })
  await expect(row).toContainText(pool)
  await expect(row.getByLabel("Allowed operations").getByText("Search", { exact: true })).toBeVisible()
})

Then("the fake vault secret is sent once and is not exposed in the browser", async ({ page }) => {
  const secret = "fake-brave-api-key"
  const requests = requestsCarrying(secret)
  expect(requests).toHaveLength(1)
  expect(requests[0]).toMatchObject({ method: "POST", url: expect.stringContaining("/api/v1/account/vault/keys") })
  expect(await secretLeaks(page, secret)).toEqual([])
  expect(consoleCarrying(secret)).toEqual([])
})

Given("Search has a keyed provider and keyless Keenable", async ({ page }) => {
  await page.goto("/account/keys")
  await expect(page.getByRole("heading", { name: "Keys and pools" })).toBeVisible()
  await page.getByRole("button", { name: "Add key", exact: true }).first().click()
  const dialog = page.getByRole("dialog", { name: "Add key" })
  await chooseOption(dialog, "Provider", "Brave Search")
  await dialog.getByLabel("Label", { exact: true }).fill("Alpha Brave")
  await dialog.getByLabel("API key", { exact: true }).fill("fake-brave-api-key")
  await dialog.getByRole("button", { name: "Save key", exact: true }).click()
  await expect(dialog).toBeHidden()
  await page.getByRole("row").filter({ hasText: "Alpha Brave" }).getByRole("button", { name: "Create pool" }).click()
  const pool = page.getByRole("dialog", { name: "Create pool" })
  await chooseOption(pool, "Project", "Alpha")
  await pool.getByLabel("Pool name").fill("Alpha Search")
  await pool.getByRole("button", { name: "Create pool", exact: true }).click()
  await expect(pool).toBeHidden()
})

When("I order Search providers by Free first", async ({ page }) => {
  await expect(page.getByRole("table", { name: "Search provider order" }).locator("tbody tr").first()).toContainText("Brave Search")
  await page.getByRole("combobox", { name: "Order by" }).click()
  await page.getByRole("option", { name: /Free first/ }).click()
})

Then("keyless Keenable is first in the Search order", async ({ page }) => {
  const row = page.getByRole("table", { name: "Search provider order" }).locator("tbody tr").first()
  await expect(row).toContainText("Keenable")
  await expect(row).toContainText("No key needed")
})

When("I add a Parallel OAuth vault key labelled {string}", async ({ page }, label: string) => {
  await page.getByRole("button", { name: "Add key", exact: true }).first().click()
  const dialog = page.getByRole("dialog", { name: "Add key" })
  await chooseOption(dialog, "Provider", "Parallel")
  await chooseOption(dialog, "Authentication", "OAuth")
  await expect(dialog.getByLabel("API key", { exact: true })).toHaveCount(0)
  await dialog.getByLabel("Label", { exact: true }).fill(label)
  await dialog.getByRole("button", { name: "Save key", exact: true }).click()
  await expect(dialog).toBeHidden()
})

When("I connect the vault key {string}", async ({ page }, label: string) => {
  await page.getByRole("button", { name: `Actions for ${label}` }).click()
  await page.getByRole("button", { name: "Connect", exact: true }).click()
})

Then("the vault OAuth dialog shows the verification code and link", async ({ page }) => {
  const dialog = page.getByRole("dialog", { name: "Connect Parallel" })
  await expect(dialog.getByText("WXYZ-1234")).toBeVisible()
  await expect(dialog.getByRole("link", { name: "Open verification page" })).toHaveAttribute("href", "https://parallel.example/device")
  await expect(dialog.getByRole("status")).toHaveText("Wait for approval.")
})

When("Parallel approves vault key {string}", async ({}, label: string) => {
  approveVaultOAuth(label)
})

Then("the vault OAuth dialog shows Connected", async ({ page }) => {
  await expect(page.getByRole("dialog", { name: "Connect Parallel" }).getByRole("status")).toHaveText("Connected")
})

Given("the Brave key {string} reports {string} USD remaining", async ({}, label: string, remaining: string) => {
  seedVaultBalance("brave", label, remaining, "USD")
})

Then("the Brave key balance shows {string} and {string}", async ({ page }, label: string, balance: string) => {
  const balances = page.locator('[aria-label="Brave Search key balances"]')
  await expect(balances).toContainText(label)
  await expect(balances).toContainText(balance)
})
