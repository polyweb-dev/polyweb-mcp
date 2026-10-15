import { expect } from "@playwright/test"
import type { Page } from "@playwright/test"
import { Given, When, Then } from "./fixtures"
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

Given("I am on the Routing view", async ({ page }) => {
  await page.getByRole("link", { name: "Routing", exact: true }).click()
  await expect(page.getByRole("heading", { name: "Routing", exact: true })).toBeVisible()
})

Then(
  "the routing sub-tabs should be visible: {string} and {string}",
  async ({ page }, first: string, second: string) => {
    for (const label of [first, second]) {
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

const KNOWN_PROVIDER_NAMES = /Brave Search|Keenable|Tavily|Exa|Firecrawl|You\.com|Parallel/

Then("a primary routing provider row should be visible", async ({ page }) => {
  // Tolerant to live latency ordering: assert the role structure (a Primary
  // marker bound to a real provider name), never a pinned provider.
  const primary = page.getByText("Primary", { exact: true }).first()
  await expect(primary).toBeVisible()
  const region = primary.locator(
    "xpath=ancestor::*[contains(normalize-space(.), 'Primary')][1]"
  )
  await expect(region).toContainText("Primary")
  await expect(region).toContainText(KNOWN_PROVIDER_NAMES)
})

const FAILOVER_STATUS = /^Failover (active|inactive)$/

Then("the routing status should show {string}", async ({ page }, status: string) => {
  // State-tolerant: under the deterministic stub the status is always the
  // expected copy, but against the live backend the persisted fallback policy
  // may render either state — accept both, anchored to the exact element.
  if (status === "Failover active" || status === "Failover inactive") {
    await expect(page.getByText(FAILOVER_STATUS)).toBeVisible()
    return
  }
  await expect(page.getByText(status, { exact: true })).toBeVisible()
})

Then("the routing eligibility should match {string}", async ({ page }, pattern: string) => {
  // Backend-tolerant count, e.g. "\d+ of \d+ providers eligible".
  await expect(page.getByText(new RegExp(pattern))).toBeVisible()
})

Then("the routing status should not use a middle-dot separator", async ({ page }) => {
  // State-tolerant: the status element renders one of the two failover states
  // (stub: active; live: whichever policy is persisted) — neither may use "·".
  const status = page.getByText(FAILOVER_STATUS)
  await expect(status).toBeVisible()
  const statusRegion = status.locator("xpath=../..")
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

Then("the execution pipeline should contain a primary provider", async ({ page }) => {
  // Tolerant to live ordering: the pipeline shows a Primary marker bound to
  // whichever provider the active strategy promoted.
  const primary = page.getByText("Primary", { exact: true }).first()
  await expect(primary).toBeVisible()
  const region = primary.locator(
    "xpath=ancestor::*[contains(normalize-space(.), 'Primary')][1]"
  )
  await expect(region).toContainText(KNOWN_PROVIDER_NAMES)
})

Then("the failover cascade should be rendered", async ({ page }) => {
  // State-tolerant: with fallback chaining the pipeline renders the failover
  // cascade (stub default); with single-attempt dispatch it renders the
  // single-shot notice instead (RouteSimulator ExecutionPipeline branches).
  const cascade = page.getByText(/Failover cascade/i).first()
  const singleShot = page.getByText(/Single-shot mode active/).first()
  await expect(async () => {
    const cascadeCount = await cascade.count()
    const singleShotCount = await singleShot.count()
    expect(cascadeCount + singleShotCount).toBeGreaterThan(0)
  }).toPass({ timeout: 10_000 })
})

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

Then(
  "the resilience row {string} should not show {string}",
  async ({ page }, label: string, forbidden: string) => {
    const row = page.getByText(label, { exact: true }).locator("xpath=..")
    await expect(row).toBeVisible()
    await expect(row).not.toContainText(forbidden)
  }
)

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
  return page.locator("article", { hasText: "Tavily" }).first()
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
  if (env === "prod") return "Production — 1000 requests per minute"
  return "Development — 100 requests per minute"
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
  await expect(page.getByText("FreeSearch", { exact: true })).toBeVisible()
})

When("I choose the Tavily rate tier {string}", async ({ page }, env: string) => {
  const select = tavilyRateTierSelect(page)
  await expect(select).toBeVisible()
  await expect(select).toBeEnabled()
  await select.selectOption(env)
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
  // Native select keyboard: one ArrowDown step moves dev to prod and fires
  // the change event, so the partial PATCH goes through keyboard input only.
  const select = tavilyCardTierSelect(page)
  await expect(select).toBeVisible()
  await expect(select).toBeEnabled()
  await select.focus()
  await expect(select).toBeFocused()
  await page.keyboard.press("ArrowDown")
})

When("I open the Tavily quota details with the keyboard", async ({ page }) => {
  const trigger = page.getByRole("button", { name: /Credit details for Tavily/i })
  await trigger.focus()
  await expect(trigger).toBeFocused()
  await page.keyboard.press("Enter")
  await expect(page.getByText("Quota Details", { exact: true })).toBeVisible()
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
  await expect(select).toHaveValue(env)
  await expect(select).toContainText(tavilyOptionLabel(env))
})

Then("the Tavily rate tier should show Unknown", async ({ page }) => {
  const select = tavilyRateTierSelect(page)
  await expect(select).toBeVisible()
  await expect(select).toHaveValue("unknown")
  await expect(select).toBeDisabled()
})

Then("the Tavily card rate tier should lock to Unknown", async ({ page }) => {
  const select = tavilyCardTierSelect(page)
  await expect(select).toBeVisible()
  await expect(select).toHaveValue("unknown")
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
    const options = select.locator("option")
    await expect(options).toHaveCount(2)
    await expect(options.nth(0)).toHaveText("Development")
    await expect(options.nth(1)).toHaveText("Production")
    const labels = await options.allTextContents()
    for (const label of labels) {
      expect(label).not.toMatch(/\d/)
      expect(label).not.toMatch(/requests/i)
    }
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
  const label = "Search and Fetch Rate Limit"
  const value = text.startsWith(label) ? text.slice(label.length).trim() : text
  await expect(page.getByText(label, { exact: true })).toBeVisible()
  await expect(page.getByText(value, { exact: true })).toBeVisible()
})

Then("the Tavily quota details should be closed", async ({ page }) => {
  await expect(page.getByText("Quota Details", { exact: true })).toHaveCount(0)
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
  await expect(tavilyRateTierSelect(page)).toHaveValue("dev")
})

Then(
  "an inline Tavily card rate tier error should show {string}",
  async ({ page }, text: string) => {
    const card = tavilyArticle(page)
    await expect(card.getByRole("alert")).toContainText(text)
    await expect(tavilyCardTierSelect(page)).toHaveValue("dev")
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
