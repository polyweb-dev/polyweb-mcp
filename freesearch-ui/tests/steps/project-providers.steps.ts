import { expect } from "@playwright/test"
import type { Locator, Page } from "@playwright/test"
import type { DataTable } from "playwright-bdd"
import { Given, Then, When } from "./fixtures"
import { projectStubId } from "./projectStub"
import {
  activateProviderConfigStub,
  configRequests,
  credentialExists,
  credentialIdOf,
  rotateCredentialElsewhere,
} from "./providerConfigStub"
import {
  chooseOption,
  consoleCarrying,
  expectWriteOnlySecretInput,
  requestsCarrying,
  secretInput,
  secretLeaks,
  watchBrowserTraffic,
} from "./providerConfigUi"

/**
 * Project Providers page and the shared credential form steps (U3 contract,
 * `.tmp/u3/ui-contract.md`). The credential form, rotate and delete steps
 * also drive the Keys tab of System Providers, which uses the same labels.
 */

const PAGE_SEGMENTS: Record<string, string> = { Providers: "providers", Settings: "settings" }

function routesTable(page: Page): Locator {
  return page.getByRole("table", { name: "Routes", exact: true })
}

/** The "Not routed" list: keys no route uses yet and providers without a key. */
function keysTable(page: Page): Locator {
  return page.getByRole("table", { name: "Not routed", exact: true })
}

function routeRow(page: Page, routeLabel: string): Locator {
  return routesTable(page).getByRole("row").filter({ hasText: routeLabel })
}

function bindingSwitch(page: Page, op: string, routeLabel: string): Locator {
  return page.getByRole("switch", { name: `Enable ${op} for ${routeLabel}`, exact: true })
}

/** Open the row menu of a key (or a route) and run one item. */
async function chooseRowAction(page: Page, trigger: string, item: string): Promise<void> {
  await page.getByRole("button", { name: trigger, exact: true }).click({ timeout: 15_000 })
  await page.getByRole("button", { name: item, exact: true }).click()
}

Given("the provider configuration is stubbed", async ({ page }) => {
  activateProviderConfigStub()
  watchBrowserTraffic(page)
})

When("I open the {word} page of project {word}", async ({ page }, pageName: string, projectName: string) => {
  const segment = PAGE_SEGMENTS[pageName]
  if (segment === undefined) throw new Error(`unknown project page ${pageName}`)
  await page.goto(`/p/${projectStubId(projectName)}/${segment}`)
})

Then("the route {string} shows {string}", async ({ page }, routeLabel: string, text: string) => {
  await expect(routeRow(page, routeLabel)).toHaveCount(1, { timeout: 15_000 })
  await expect(routeRow(page, routeLabel)).toContainText(text)
})

Then(
  "the keys table lists {string} with {string}",
  async ({ page }, label: string, text: string) => {
    const row = keysTable(page).getByRole("row").filter({ hasText: label })
    await expect(row).toHaveCount(1, { timeout: 15_000 })
    await expect(row).toContainText(text)
  }
)

Then("the keys table does not list {string}", async ({ page }, label: string) => {
  await expect(keysTable(page)).toBeVisible()
  await expect(keysTable(page).getByRole("row").filter({ hasText: label })).toHaveCount(0)
})

Then("the capacity allocations read:", async ({ page }, table: DataTable) => {
  const explanations = page.getByTestId("allocation-explanation")
  for (const row of table.hashes()) {
    const item = explanations.filter({ hasText: row.text })
    await expect(item).toHaveCount(1, { timeout: 15_000 })
    await expect(item).toContainText(row.badge)
  }
})

When(
  "I add a route on the key {string} with route label {string}",
  async ({ page }, credential: string, routeLabel: string) => {
    await page.getByRole("button", { name: `Add route for ${credential}`, exact: true }).click()
    const dialog = page.getByRole("dialog", { name: "Add route", exact: true })
    await expect(dialog.getByRole("combobox", { name: "Key", exact: true })).toContainText(credential)
    // The priority is computed so the route goes last; no number is typed.
    await expect(dialog.getByLabel("Priority", { exact: true })).toHaveCount(0)
    await dialog.getByLabel("Label", { exact: true }).fill(routeLabel)
    await dialog.getByRole("button", { name: "Add route", exact: true }).click()
  }
)

Then("the route {string} is last in the route order", async ({ page }, routeLabel: string) => {
  await expect(routeRow(page, routeLabel)).toHaveCount(1, { timeout: 15_000 })
  await expect(routesTable(page).getByRole("row").last()).toContainText(routeLabel)
})

Then("the binding create request carried no enabled operations", async () => {
  await expect.poll(() => configRequests("POST", /\/bindings$/).length).toBe(1)
  const body = configRequests("POST", /\/bindings$/)[0].body ?? {}
  expect(body).not.toHaveProperty("enabled_operations")
  expect(body.credential_id).toBe(credentialIdOf("Shared Tavily"))
  expect(body.route_label).toBe("tavily-main")
})

Then(
  "the {word} toggle of binding {string} is {word}",
  async ({ page }, op: string, routeLabel: string, stateWord: string) => {
    const toggle = bindingSwitch(page, op, routeLabel)
    await expect(toggle).toBeVisible({ timeout: 15_000 })
    if (stateWord === "on") await expect(toggle).toBeChecked()
    else if (stateWord === "off") await expect(toggle).not.toBeChecked()
    else if (stateWord === "disabled") await expect(toggle).toBeDisabled()
    else throw new Error(`unknown toggle state ${stateWord}`)
  }
)

When("I turn {word} {word} for binding {string}", async ({ page }, _state: string, op: string, routeLabel: string) => {
  await bindingSwitch(page, op, routeLabel).click()
})

Then(
  "the {word} toggle of binding {string} is read-only {string}",
  async ({ page }, op: string, routeLabel: string, value: string) => {
    await expect(routeRow(page, routeLabel)).toHaveCount(1, { timeout: 15_000 })
    await expect(bindingSwitch(page, op, routeLabel)).toHaveCount(0)
    await expect(routeRow(page, routeLabel)).toContainText(value)
  }
)

Then("the last binding update enabled exactly {string}", async ({}, list: string) => {
  const expected = list.split(",").map((s) => s.trim())
  await expect
    .poll(() => {
      const patches = configRequests("PATCH", /\/bindings\/[0-9a-f-]{36}$/)
      return patches[patches.length - 1]?.body?.enabled_operations ?? null
    })
    .toEqual(expected)
})

When("I remove the route {string}", async ({ page }, routeLabel: string) => {
  await chooseRowAction(page, `Actions for route ${routeLabel}`, "Remove route")
  await page
    .getByRole("dialog", { name: `Remove route ${routeLabel}`, exact: true })
    .getByRole("button", { name: "Remove route", exact: true })
    .click()
})

Then("the route {string} is removed", async ({ page }, routeLabel: string) => {
  await expect.poll(() => configRequests("DELETE", /\/bindings\/[0-9a-f-]{36}$/).length).toBe(1)
  await expect(page.getByRole("button", { name: `Actions for route ${routeLabel}`, exact: true })).toHaveCount(0)
})

/**
 * Fill and submit the shared credential form (project "Add provider key" or
 * the System Providers Keys tab "Add key"): Provider, Label, Authentication, the write-only
 * "API key" input, "Save key".
 */
async function submitCredentialForm(
  page: Page,
  openButton: string,
  provider: string,
  label: string,
  secret: string | null
): Promise<void> {
  await page.getByRole("button", { name: openButton, exact: true }).click()
  const dialog = page.getByRole("dialog", { name: openButton, exact: true })
  await chooseOption(dialog, "Provider", provider)
  await dialog.getByLabel("Label", { exact: true }).fill(label)
  const authentication = dialog.getByRole("group", { name: "Authentication", exact: true })
  if (secret === null) {
    await authentication.getByRole("button", { name: "OAuth", exact: true }).click()
    await expect(secretInput(dialog, "API key")).toHaveCount(0)
  } else {
    const apiKeyMode = authentication.getByRole("button", { name: "API key", exact: true })
    if ((await apiKeyMode.count()) > 0) await apiKeyMode.click()
    const input = secretInput(dialog, "API key")
    await expectWriteOnlySecretInput(input)
    await input.fill(secret)
  }
  await dialog.getByRole("button", { name: "Save key", exact: true }).click()
}

When(
  "I add a provider key for {string} labelled {string} with API key {string}",
  async ({ page }, provider: string, label: string, secret: string) => {
    await submitCredentialForm(page, "Add provider key", provider, label, secret)
  }
)

When(
  "I add a private OAuth key for {string} labelled {string}",
  async ({ page }, provider: string, label: string) => {
    await submitCredentialForm(page, "Add provider key", provider, label, null)
  }
)

When(
  "I add a system credential for {string} labelled {string} with API key {string}",
  async ({ page }, provider: string, label: string, secret: string) => {
    await submitCredentialForm(page, "Add key", provider, label, secret)
  }
)

When(
  "I add a system OAuth credential for {string} labelled {string}",
  async ({ page }, provider: string, label: string) => {
    await submitCredentialForm(page, "Add key", provider, label, null)
  }
)

Then("the last credential create request used OAuth without a secret", async () => {
  await expect.poll(() => configRequests("POST", /\/credentials$/).length).toBeGreaterThan(0)
  const creates = configRequests("POST", /\/credentials$/)
  const body = creates[creates.length - 1].body ?? {}
  expect(body.auth_mode).toBe("oauth")
  expect(body.secret ?? null).toBeNull()
})

Then(
  "the secret {string} was sent only in the credential {word} request",
  async ({}, secret: string, kind: string) => {
    const path = kind === "rotate" ? /\/credentials\/[0-9a-f-]{36}\/rotate$/ : /\/credentials$/
    await expect.poll(() => requestsCarrying(secret).length).toBeGreaterThan(0)
    const carriers = requestsCarrying(secret)
    expect(carriers).toHaveLength(1)
    expect(carriers[0].method).toBe("POST")
    const url = new URL(carriers[0].url)
    expect(url.pathname).toMatch(path)
    expect(url.search).not.toContain(secret)
    expect(JSON.parse(carriers[0].body).secret).toBe(secret)
  }
)

Then(
  "the secret {string} is nowhere in the page, browser storage, URL or console",
  async ({ page }, secret: string) => {
    // Let the form settle (success, failure or close) before looking.
    await expect.poll(() => secretLeaks(page, secret)).toEqual([])
    expect(consoleCarrying(secret)).toEqual([])
  }
)

Then("no secret input holds a value", async ({ page }) => {
  const inputs = page.locator('input[type="password"]')
  const count = await inputs.count()
  for (let index = 0; index < count; index += 1) await expect(inputs.nth(index)).toHaveValue("")
})

When("someone else rotates the key {string}", async ({ page }, label: string) => {
  // The page has rendered the current generation before the change.
  await expect(page.getByRole("button", { name: `Actions for ${label}`, exact: true })).toBeVisible({
    timeout: 15_000,
  })
  rotateCredentialElsewhere(label)
})

When("I rotate the key {string} with {string}", async ({ page }, label: string, secret: string) => {
  await chooseRowAction(page, `Actions for ${label}`, "Rotate key")
  const dialog = page.getByRole("dialog", { name: `Rotate key for ${label}`, exact: true })
  const input = secretInput(dialog, "New API key")
  await expectWriteOnlySecretInput(input)
  await input.fill(secret)
  await dialog.getByRole("button", { name: "Rotate key", exact: true }).click()
})

Then("the last rotate request expected generation {int}", async ({}, generation: number) => {
  await expect.poll(() => configRequests("POST", /\/rotate$/).length).toBeGreaterThan(0)
  const rotates = configRequests("POST", /\/rotate$/)
  expect(rotates[rotates.length - 1].body?.expected_generation).toBe(generation)
})

When("I delete the key {string} and confirm", async ({ page }, label: string) => {
  await chooseRowAction(page, `Actions for ${label}`, "Delete key")
  await page.getByRole("dialog").getByRole("button", { name: "Delete key", exact: true }).click()
})

Then("the stub no longer holds the credential {string}", async ({}, label: string) => {
  await expect.poll(() => credentialExists(label)).toBe(false)
})

Then("the providers page offers no configuration controls", async ({ page }) => {
  await expect(routesTable(page)).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole("button", { name: "Add provider key", exact: true })).toHaveCount(0)
  await expect(page.getByRole("button", { name: /^Actions for / })).toHaveCount(0)
  await expect(page.getByRole("button", { name: /^Add route/ })).toHaveCount(0)
  const switches = page.getByRole("switch")
  const count = await switches.count()
  for (let index = 0; index < count; index += 1) await expect(switches.nth(index)).toBeDisabled()
})

Then("the providers page offers no way to reveal or copy a key", async ({ page }) => {
  // Write-only: a saved key has metadata only, never a reveal, copy or
  // shown-once affordance.
  await expect(keysTable(page)).toBeVisible()
  await expect(page.getByRole("button", { name: /reveal|copy key|show key|burn/i })).toHaveCount(0)
  await expect(page.getByText(/shown once/i)).toHaveCount(0)
})
