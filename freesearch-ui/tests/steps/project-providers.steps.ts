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
  confirmIfAsked,
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
 * also drive the System credentials page, which uses the same labels.
 */

const PAGE_SEGMENTS: Record<string, string> = { Providers: "providers", Settings: "settings" }

function providerRegion(page: Page, name: string): Locator {
  return page.getByRole("region", { name: `${name} provider`, exact: true })
}

function credentialsTable(page: Page, name: string): Locator {
  return page.getByRole("table", { name: `${name} credentials`, exact: true })
}

function bindingSwitch(page: Page, op: string, routeLabel: string): Locator {
  return page.getByRole("switch", { name: `Enable ${op} for ${routeLabel}`, exact: true })
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

Then("the {string} provider shows {string}", async ({ page }, name: string, text: string) => {
  await expect(providerRegion(page, name)).toContainText(text, { timeout: 15_000 })
})

Then(
  "the {string} credentials table lists {string} with {string} and {string}",
  async ({ page }, name: string, label: string, owner: string, auth: string) => {
    const row = credentialsTable(page, name).getByRole("row").filter({ hasText: label })
    await expect(row).toHaveCount(1, { timeout: 15_000 })
    await expect(row).toContainText(owner)
    await expect(row).toContainText(auth)
  }
)

Then(
  "the {string} credentials table does not list {string}",
  async ({ page }, name: string, label: string) => {
    await expect(credentialsTable(page, name)).toBeVisible()
    await expect(credentialsTable(page, name).getByRole("row").filter({ hasText: label })).toHaveCount(0)
  }
)

Then("the capacity allocations read:", async ({ page }, table: DataTable) => {
  const explanations = page.getByTestId("allocation-explanation")
  for (const row of table.hashes()) {
    const item = explanations.filter({ hasText: row.text })
    await expect(item).toHaveCount(1, { timeout: 15_000 })
    await expect(item).toContainText(row.badge)
  }
})

When(
  "I add a {string} binding to {string} with route label {string}",
  async ({ page }, name: string, credential: string, routeLabel: string) => {
    await providerRegion(page, name).getByRole("button", { name: "Add binding", exact: true }).click()
    await chooseOption(page, "Credential", credential)
    await page.getByLabel("Route label", { exact: true }).fill(routeLabel)
    await expect(page.getByLabel("Priority", { exact: true })).toHaveValue("100")
    await page.getByRole("button", { name: "Create binding", exact: true }).click()
  }
)

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

When("I turn on {word} for binding {string}", async ({ page }, op: string, routeLabel: string) => {
  await bindingSwitch(page, op, routeLabel).click()
})

Then("the last binding update enabled exactly {string}", async ({}, list: string) => {
  await expect.poll(() => configRequests("PATCH", /\/bindings\/[0-9a-f-]{36}$/).length).toBeGreaterThan(0)
  const patches = configRequests("PATCH", /\/bindings\/[0-9a-f-]{36}$/)
  const body = patches[patches.length - 1].body ?? {}
  expect(body.enabled_operations).toEqual(list.split(",").map((s) => s.trim()))
})

When("I remove the binding {string}", async ({ page }, routeLabel: string) => {
  await page.getByRole("button", { name: `Remove binding ${routeLabel}`, exact: true }).click()
  await confirmIfAsked(page, `Remove binding`)
})

Then("the binding {string} is removed", async ({ page }, routeLabel: string) => {
  await expect.poll(() => configRequests("DELETE", /\/bindings\/[0-9a-f-]{36}$/).length).toBe(1)
  await expect(page.getByRole("button", { name: `Remove binding ${routeLabel}`, exact: true })).toHaveCount(0)
})

/**
 * Fill and submit the shared credential form (project "Add provider key" or
 * "Add system credential"): Provider, Label, Auth mode, the write-only
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
  await chooseOption(page, "Provider", provider)
  await page.getByLabel("Label", { exact: true }).fill(label)
  if (secret === null) {
    await page.getByRole("radio", { name: "OAuth", exact: true }).check()
    await expect(secretInput(page, "API key")).toHaveCount(0)
  } else {
    const apiKeyMode = page.getByRole("radio", { name: "API key", exact: true })
    if ((await apiKeyMode.count()) > 0) await apiKeyMode.check()
    const input = secretInput(page, "API key")
    await expectWriteOnlySecretInput(input)
    await input.fill(secret)
  }
  await page.getByRole("button", { name: "Save key", exact: true }).click()
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
    await submitCredentialForm(page, "Add system credential", provider, label, secret)
  }
)

When(
  "I add a system OAuth credential for {string} labelled {string}",
  async ({ page }, provider: string, label: string) => {
    await submitCredentialForm(page, "Add system credential", provider, label, null)
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
  await expect(page.getByRole("button", { name: `Rotate key ${label}`, exact: true })).toBeVisible({
    timeout: 15_000,
  })
  rotateCredentialElsewhere(label)
})

When("I rotate the key {string} with {string}", async ({ page }, label: string, secret: string) => {
  await page.getByRole("button", { name: `Rotate key ${label}`, exact: true }).click()
  const dialog = page.getByRole("dialog")
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
  await page.getByRole("button", { name: `Delete key ${label}`, exact: true }).click()
  await page.getByRole("dialog").getByRole("button", { name: "Delete key", exact: true }).click()
})

Then("the stub no longer holds the credential {string}", async ({}, label: string) => {
  await expect.poll(() => credentialExists(label)).toBe(false)
})

Then("the providers page offers no configuration controls", async ({ page }) => {
  await expect(page.getByRole("region", { name: /provider$/ }).first()).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole("button", { name: "Add binding", exact: true })).toHaveCount(0)
  await expect(page.getByRole("button", { name: "Add provider key", exact: true })).toHaveCount(0)
  await expect(page.getByRole("button", { name: /^Remove binding / })).toHaveCount(0)
  await expect(page.getByRole("button", { name: /^Rotate key / })).toHaveCount(0)
  await expect(page.getByRole("button", { name: /^Delete key / })).toHaveCount(0)
  await expect(page.getByRole("button", { name: /^(Connect|Disconnect) / })).toHaveCount(0)
  const switches = page.getByRole("switch")
  const count = await switches.count()
  for (let index = 0; index < count; index += 1) await expect(switches.nth(index)).toBeDisabled()
})

Then("the providers page offers no way to reveal or copy a key", async ({ page }) => {
  // Write-only: a saved key has metadata only, never a reveal, copy or
  // shown-once affordance.
  await expect(page.getByRole("region", { name: /provider$/ }).first()).toBeVisible()
  await expect(page.getByRole("button", { name: /reveal|copy key|show key|burn/i })).toHaveCount(0)
  await expect(page.getByText(/shown once/i)).toHaveCount(0)
})
