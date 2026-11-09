import { expect } from "@playwright/test"
import type { Page } from "@playwright/test"
import { Given, When, Then } from "./fixtures"
import { providerQuotaSurface } from "./providerQuotaUi"
import {
  delayStubbedProviderPatch,
  failStubbedDashboardGet,
  failStubbedProvidersGet,
  holdTavilyDashboardRefresh,
  setStubbedProviderLimits,
  setStubbedSecretPresence,
  setTavilyStatusReadbackDev,
  setTavilyStatusReadbackInvalid,
  setTavilyStatusReadbackMissing,
  setTavilyStatusReadbackProd,
  stubbedProviderPatchBodies,
  stubbedSyncCalls,
  stubbedTestCalls,
  stubbedUsageCalls,
  tavilyConsumedDevLimits,
  tavilyConsumedProdLimits,
  tavilyCreditLimits,
  tavilyGrantLimits,
  tavilyProdCreditLimits,
} from "./backendStub"

When("I click the {string} button", async ({ page }, buttonLabel: string) => {
  await page.getByRole("button", { name: buttonLabel, exact: true }).click()
})

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

// ---------------------------------------------------------------------------
// Tavily rate-tier dropdown (PLAN 5.2 BDD list, Settings registry) plus the
// Tavily card tier slot (FIX-AC3 tier control, PLAN 10.4/10.5).
//
// All backend traffic is stubbed (@stub Before hook installs backendStub).
// The stored key environment comes from GET /api/v1/providers readback
// (setTavilyStatusReadback* fixtures); the dashboard fixtures come from the
// stubbed provider limits; the one partial PATCH persists the choice.
// Settings assertions use the registry select; card assertions scope every
// selector to the Tavily article, so the popover portal (document.body) never
// leaks into outside-text checks. Assertions use roles and labels only.
//
// Intentional FIX replacements: the Settings dev/prod scenarios assert the
// open-popover `Search and Fetch Rate Limit X/Y requests per minute` row
// instead of the retired outside minute-count text, and the retired
// `Tavily minute headroom should show` step is deleted with them.
//
// Shared card-tier steps live in provider-credits.steps.ts and are reused
// here (one definition per text): `I choose the Tavily card rate tier`,
// `the Tavily card rate tier should show`, `... should be disabled while
// pending`, `the Tavily card read-only/keyless rate text should show`, and
// `the Tavily details control regains focus`. This file defines only the
// routing-tier additions.
// ---------------------------------------------------------------------------

function tavilyArticle(page: Page) {
  return providerQuotaSurface(page, "Tavily")
}

function tavilyRateTierSelect(page: Page) {
  return page.getByRole("combobox", { name: "Tavily rate tier (key environment)", exact: true })
}

function tavilyCardTierSelect(page: Page) {
  return tavilyArticle(page).getByRole("combobox", {
    name: "Tavily rate tier (key environment)",
    exact: true,
  })
}

function tavilyOptionLabel(env: string): string {
  return env === "prod" ? "Production" : "Development"
}

function tavilyPatches() {
  return stubbedProviderPatchBodies().filter((entry) => entry.backendId === "tavily")
}

Given("the Tavily stored key environment is {string}", async ({ page }, env: string) => {
  void page
  if (env === "prod") setTavilyStatusReadbackProd()
  else setTavilyStatusReadbackDev()
})

Given("the Tavily stored key environment is absent", async ({ page }) => {
  void page
  setTavilyStatusReadbackMissing()
})

Given("the Tavily stored key environment is invalid", async ({ page }) => {
  void page
  setTavilyStatusReadbackInvalid()
})

Given("the Tavily key is keyless", async ({ page }) => {
  void page
  setStubbedSecretPresence("tavily", "keyless_public")
})

Given("the Tavily dashboard shows dev minute headroom", async ({ page }) => {
  void page
  setStubbedProviderLimits(tavilyCreditLimits())
})

Given("the Tavily dashboard shows prod minute headroom", async ({ page }) => {
  void page
  setStubbedProviderLimits(tavilyProdCreditLimits())
})

Given("the Tavily dashboard shows consumed dev headroom", async ({ page }) => {
  void page
  setStubbedProviderLimits(tavilyConsumedDevLimits())
})

Given("the Tavily dashboard shows consumed prod headroom", async ({ page }) => {
  void page
  setStubbedProviderLimits(tavilyConsumedProdLimits())
})

Given("the Tavily dashboard keeps stored grants", async ({ page }) => {
  void page
  setStubbedProviderLimits(tavilyGrantLimits())
})

Given("the Tavily dashboard refresh will fail with {string}", async ({ page }, message: string) => {
  void page
  failStubbedDashboardGet(message)
})

Given("the Tavily providers refresh will fail with {string}", async ({ page }, message: string) => {
  void page
  failStubbedProvidersGet(message)
})

Given(
  "the Tavily dashboard refresh is held for {int} milliseconds",
  async ({ page }, ms: number) => {
    void page
    holdTavilyDashboardRefresh(ms)
  }
)

Given(
  "the Tavily rate tier PATCH is delayed by {int} milliseconds",
  async ({ page }, ms: number) => {
    void page
    delayStubbedProviderPatch("tavily", ms)
  }
)

Given("the Tavily key becomes keyless before the PATCH settles", async ({ page }) => {
  void page
  setStubbedSecretPresence("tavily", "keyless_public")
})

When("I reload the web application", async ({ page }) => {
  await page.reload()
  await expect(page.getByText("Polyweb", { exact: true })).toBeVisible()
})

When("I choose the Tavily rate tier {string}", async ({ page }, env: string) => {
  const select = tavilyRateTierSelect(page)
  await expect(select).toBeVisible()
  await expect(select).toBeEnabled()
  await select.click()
  await page.getByRole("listbox").getByRole("option", { name: new RegExp(`^${tavilyOptionLabel(env)}`) }).click()
})

When("I focus the Tavily rate tier select", async ({ page }) => {
  const select = tavilyRateTierSelect(page)
  await expect(select).toBeVisible()
  await select.focus()
  await expect(select).toBeFocused()
})

When("I focus the Tavily card rate tier select", async ({ page }) => {
  const select = tavilyCardTierSelect(page)
  await expect(select).toBeVisible()
  await select.focus()
  await expect(select).toBeFocused()
})

When("I choose the Tavily card rate tier with the keyboard", async ({ page }) => {
  // Open at the current value, move from dev to prod, and commit the choice.
  const select = tavilyCardTierSelect(page)
  await expect(select).toBeVisible()
  await expect(select).toBeEnabled()
  await select.focus()
  await expect(select).toBeFocused()
  await page.keyboard.press("Enter")
  await page.keyboard.press("ArrowDown")
  await page.keyboard.press("Enter")
})

When("I open the Tavily quota details with the keyboard", async ({ page }) => {
  const trigger = page.getByRole("button", { name: /Credit details for Tavily/i })
  await trigger.focus()
  await expect(trigger).toBeFocused()
  await page.keyboard.press("Enter")
  await expect(page.getByText("Quota details", { exact: true })).toBeVisible()
})

When("I cancel the Tavily quota details", async ({ page }) => {
  await page.keyboard.press("Escape")
})

When("I attempt a registry drag from the Tavily rate tier select", async ({ page }) => {
  const select = tavilyRateTierSelect(page)
  await expect(select).toBeVisible()
  const row = page.getByText("Tavily", { exact: true }).locator("xpath=ancestor::tr[1]")
  const before = await row.getAttribute("class")
  const box = await select.boundingBox()
  if (box !== null) {
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.down()
    await page.mouse.move(box.x + box.width / 2 + 40, box.y + 30, { steps: 4 })
    await page.mouse.up()
  }
  await expect.poll(async () => row.getAttribute("class")).toBe(before)
})

Then("the Tavily rate tier should show {string}", async ({ page }, env: string) => {
  const select = tavilyRateTierSelect(page)
  await expect(select).toBeVisible()
  await expect(select).toContainText(tavilyOptionLabel(env))
})

Then("the Tavily rate tier should show Unknown", async ({ page }) => {
  const select = tavilyRateTierSelect(page)
  await expect(select).toBeVisible()
  await expect(select).toContainText("Unknown")
  await expect(select).toBeDisabled()
})

Then("the Tavily card rate tier should lock to Unknown", async ({ page }) => {
  const select = tavilyCardTierSelect(page)
  await expect(select).toBeVisible()
  await expect(select).toContainText("Unknown")
  await expect(select).toBeDisabled()
})

Then("the Tavily rate tier should be disabled while pending", async ({ page }) => {
  await expect(tavilyRateTierSelect(page)).toBeDisabled()
})

Then(
  "the Tavily card tier slot should sit beside the card buttons",
  async ({ page }) => {
    const select = tavilyCardTierSelect(page)
    await expect(select).toBeVisible()
    // The slot composes beside the buttons in one flexible action group:
    // the select shares its grandparent flex container with a card button.
    const group = select.locator("xpath=../..")
    await expect(group.getByRole("button").first()).toBeVisible()
    expect(await group.getAttribute("class")).toContain("flex")
    const selectBox = await select.boundingBox()
    const buttonBox = await group.getByRole("button").first().boundingBox()
    expect(selectBox).not.toBeNull()
    expect(buttonBox).not.toBeNull()
    if (selectBox !== null && buttonBox !== null) {
      const selectCenter = selectBox.y + selectBox.height / 2
      const buttonCenter = buttonBox.y + buttonBox.height / 2
      expect(Math.abs(selectCenter - buttonCenter)).toBeLessThanOrEqual(48)
    }
  }
)

Then(
  "the Tavily card tier options should be compact without numeric rate text",
  async ({ page }) => {
    const select = tavilyCardTierSelect(page)
    await expect(select).toBeVisible()
    await select.click()
    const options = page.getByRole("listbox").getByRole("option")
    await expect(options).toHaveCount(2)
    await expect(options.nth(0)).toHaveText("Development")
    await expect(options.nth(1)).toHaveText("Production")
    const labels = await options.allTextContents()
    for (const label of labels) {
      expect(label).not.toMatch(/\d/)
      expect(label).not.toMatch(/requests/i)
    }
    await page.keyboard.press("Escape")
  }
)

Then("the Tavily card should contain no outside rate text", async ({ page }) => {
  // Scoped to the Tavily article: the popover portal mounts on document.body,
  // so open-popover rate rows never leak into this check. Compact card text
  // carries no numeric rate counts, no minute rows, and no old "N of M" text.
  const card = tavilyArticle(page)
  await expect(card).not.toContainText("requests per minute")
  await expect(card).not.toContainText("requests/min")
  await expect(card).not.toContainText("Minute headroom")
  await expect(card).not.toContainText("Search and Fetch Rate Limit")
  await expect(card.getByText(/\d+ of \d+/)).toHaveCount(0)
})

Then("the Tavily rate row should show {string}", async ({ page }, text: string) => {
  // Open-popover assertion for the combined FIX-Q2 row, e.g.
  // "Search and Fetch Rate Limit 100/100 requests per minute" or the
  // immediate-ceiling "Search and Fetch Rate Limit unknown/1000 requests
  // per minute". The label and the value are sibling spans, so assert both.
  const label = "Search and fetch rate limit"
  const value = text.startsWith(label) ? text.slice(label.length).trim() : text
  await expect(page.getByText(label, { exact: true })).toBeVisible()
  await expect(page.getByText(value, { exact: true })).toBeVisible()
})

Then("the Tavily quota details should be closed", async ({ page }) => {
  await expect(page.getByText("Quota details", { exact: true })).toHaveCount(0)
})

Then(
  "exactly one Tavily rate tier PATCH should carry {string}",
  async ({ page }, env: string) => {
    void page
    await expect
      .poll(() => tavilyPatches().length, { timeout: 10_000 })
      .toBe(1)
    const [entry] = tavilyPatches()
    expect(entry.body).toEqual({ tavily_key_environment: env })
  }
)

Then("no Tavily rate tier PATCH should exist", async ({ page }) => {
  void page
  expect(tavilyPatches()).toHaveLength(0)
})

Then("the Tavily Credits should still show {string}", async ({ page }, text: string) => {
  await expect(page.getByText(new RegExp(escapeRegExp(text)))).toBeVisible()
})

Then("an inline Tavily rate tier error should show {string}", async ({ page }, text: string) => {
  await expect(page.getByRole("alert")).toContainText(text)
  await expect(tavilyRateTierSelect(page)).toContainText("Development")
})

Then(
  "an inline Tavily card rate tier error should show {string}",
  async ({ page }, text: string) => {
    const card = tavilyArticle(page)
    await expect(card.getByRole("alert")).toContainText(text)
    await expect(tavilyCardTierSelect(page)).toContainText("Development")
  }
)

Then("the Tavily keyless rate text should show {string}", async ({ page }, text: string) => {
  await expect(page.getByText(text, { exact: true })).toBeVisible()
  await expect(tavilyRateTierSelect(page)).toHaveCount(0)
})

Then("the Tavily read-only rate text should show {string}", async ({ page }, text: string) => {
  await expect(page.getByText(text, { exact: true })).toBeVisible()
  await expect(tavilyRateTierSelect(page)).toHaveCount(0)
})

Then("a Tavily confirmation unavailable note should show", async ({ page }) => {
  await expect(page.getByText("Confirmation unavailable", { exact: true })).toBeVisible()
  await expect(tavilyRateTierSelect(page)).toBeDisabled()
})

Then("a Tavily card confirmation unavailable note should show", async ({ page }) => {
  const card = tavilyArticle(page)
  await expect(card.getByText("Confirmation unavailable", { exact: true })).toBeVisible()
  await expect(tavilyCardTierSelect(page)).toBeDisabled()
})

Then("no Tavily usage requests should exist", async ({ page }) => {
  void page
  expect(stubbedUsageCalls()).toHaveLength(0)
})

Then("no Tavily provider test requests should exist", async ({ page }) => {
  void page
  expect(stubbedTestCalls()).toHaveLength(0)
})

Then("no Tavily force-sync requests should exist", async ({ page }) => {
  void page
  expect(stubbedSyncCalls()).toHaveLength(0)
})
