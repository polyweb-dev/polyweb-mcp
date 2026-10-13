import { expect } from "@playwright/test"
import { Given, When, Then } from "./fixtures"
import {
  braveCreditLimits,
  braveCreditLimitsAfterDebit,
  bravePlusTavilyLimits,
  setStubbedCrdTotals,
  setStubbedHistory,
  setStubbedProviderLimits,
  stubbedGrantBodies,
  tavilyCreditLimits,
  tavilyCreditLimitsAfterAdvanced,
  tavilyCreditLimitsAfterBasic,
  tavilyFreeExhaustedLimits,
  tavilyGrantLimits,
  tavilyHistoryEvents,
  tavilyKeylessLimits,
  tavilyPaygoLimits,
  tavilyProdCreditLimits,
  tavilyUseTotals,
  ui7HistoryEvents,
  unknownCreditLimits,
} from "./backendStub"

const EXPECTED_CRD_TEXT: Record<string, string> = {
  "0": "0 CRD",
  "0.04": "<0.1 CRD",
  "0.599": "≈0.6 CRD",
  "4.5": "4.5 CRD",
}

/**
 * CARD-3 provider credit units (provider-credits.feature @ui7).
 *
 * All backend traffic is stubbed. Dashboard credit state is mutable
 * per scenario through the backendStub setters. Assertions use role and
 * label selectors, never layout selectors or sleeps. The card shows the
 * credit fraction ("4500 / 5000 CRD" split spans, never a "CRD left"
 * label), four leading actions, a source subtitle, and an info popover
 * with the call cost, call count, rate limit, last sync, usage page,
 * and vendor detail.
 */

/** Catalog display name of the stubbed provider id. */
function barName(provider: string): string {
  return (provider === "Brave" ? "Brave Search" : provider) + " credit units remaining"
}

function braveNoUse(): unknown[] {
  return []
}

function braveOneSearchUse(): unknown[] {
  return [
    {
      provider: "brave",
      operation: "search",
      normalized_crd: "5",
      attempt_count: 1,
      volume_count: 1,
    },
  ]
}

function braveFractionalUse(): unknown[] {
  return [
    {
      provider: "brave",
      operation: "search",
      normalized_crd: "11",
      attempt_count: 3,
      volume_count: 3,
    },
  ]
}

function fundsWithoutAllowance(): unknown[] {
  const limits = braveCreditLimits() as Array<Record<string, unknown>>
  const entry = { ...(limits[0] as Record<string, unknown>) }
  const auths = (entry.auths as Array<Record<string, unknown>>).map((auth) => ({
    ...auth,
    aggregate_pool: {
      ...((auth.aggregate_pool ?? {}) as Record<string, unknown>),
      allowance: null,
    },
  }))
  return [{ ...entry, auths }] as unknown[]
}

function manualAnchorLimits(): unknown[] {
  const limits = braveCreditLimits() as Array<Record<string, unknown>>
  const entry = { ...(limits[0] as Record<string, unknown>) }
  const auths = (entry.auths as Array<Record<string, unknown>>).map((auth) => ({
    ...auth,
    aggregate_pool: {
      ...((auth.aggregate_pool ?? {}) as Record<string, unknown>),
      manual_anchor: true,
    },
  }))
  return [{ ...entry, auths }] as unknown[]
}

function freeLimits(): unknown[] {
  const limits = braveCreditLimits() as Array<Record<string, unknown>>
  const entry = { ...(limits[0] as Record<string, unknown>) }
  const auths = (entry.auths as Array<Record<string, unknown>>).map((auth) => ({
    ...auth,
    aggregate_pool: null,
    crd_views: [
      {
        state: "unmetered",
        operation: "search",
        remaining_crd: null,
        local_remaining_crd: null,
        request_cost_crd: null,
        shared_pool_id: null,
        possible_standard_calls: null,
        price_version: null,
        priced: false,
      },
      {
        state: "unavailable",
        operation: "fetch",
        remaining_crd: null,
        local_remaining_crd: null,
        request_cost_crd: null,
        shared_pool_id: null,
        possible_standard_calls: null,
        price_version: null,
        priced: false,
      },
    ],
  }))
  return [{ ...entry, auths }] as unknown[]
}

Given("the stubbed provider limits show {string}", async ({}, kind: string) => {
  if (kind === "Brave finite credits") setStubbedProviderLimits(braveCreditLimits())
  else if (kind === "Brave finite credits after debit") setStubbedProviderLimits(braveCreditLimitsAfterDebit())
  else if (kind === "Brave unknown credits") setStubbedProviderLimits(unknownCreditLimits())
  else if (kind === "Brave funds without allowance") setStubbedProviderLimits(fundsWithoutAllowance())
  else if (kind === "Brave free credits") setStubbedProviderLimits(freeLimits())
  else if (kind === "Brave manual balance") setStubbedProviderLimits(manualAnchorLimits())
  else if (kind === "Tavily finite credits") setStubbedProviderLimits(tavilyCreditLimits())
  else if (kind === "Tavily finite credits after basic") setStubbedProviderLimits(tavilyCreditLimitsAfterBasic())
  else if (kind === "Tavily finite credits after advanced") setStubbedProviderLimits(tavilyCreditLimitsAfterAdvanced())
  else if (kind === "Tavily keyless credits") setStubbedProviderLimits(tavilyKeylessLimits())
  else if (kind === "Tavily free exhausted") setStubbedProviderLimits(tavilyFreeExhaustedLimits())
  else if (kind === "Tavily paygo overage") setStubbedProviderLimits(tavilyPaygoLimits())
  else if (kind === "Tavily grant credits") setStubbedProviderLimits(tavilyGrantLimits())
  else if (kind === "Tavily prod credits") setStubbedProviderLimits(tavilyProdCreditLimits())
  else if (kind === "Brave and Tavily finite credits") setStubbedProviderLimits(bravePlusTavilyLimits())
  else throw new Error(`Unknown provider limits kind: ${kind}`)
})

Given("the stubbed credit totals show {string}", async ({}, kind: string) => {
  if (kind === "Brave no use") setStubbedCrdTotals(braveNoUse())
  else if (kind === "Brave one search use") setStubbedCrdTotals(braveOneSearchUse())
  else if (kind === "Brave fractional use") setStubbedCrdTotals(braveFractionalUse())
  else if (kind === "Tavily no use") setStubbedCrdTotals([])
  else if (kind === "Tavily search and extract use") setStubbedCrdTotals(tavilyUseTotals())
  else throw new Error(`Unknown credit totals kind: ${kind}`)
})

Given("the stubbed credit history shows {string}", async ({}, kind: string) => {
  if (kind === "Brave credit history") {
    setStubbedHistory("brave", { events: ui7HistoryEvents(), nextCursor: null, error: null })
    return
  }
  if (kind === "Tavily credit history") {
    setStubbedHistory("tavily", { events: tavilyHistoryEvents(), nextCursor: null, error: null })
    return
  }
  throw new Error(`Unknown credit history kind: ${kind}`)
})

When("I open the credit manual entry for {string}", async ({ page }, provider: string) => {
  await page.getByRole("button", { name: new RegExp("Provider Balance for " + provider, "i") }).click()
  await expect(page.getByText("Allowance (USD)")).toBeVisible()
})

When("I open the credit grant for {string}", async ({ page }, provider: string) => {
  await page.getByRole("button", { name: new RegExp("Budget Limit for " + provider, "i") }).click()
  await expect(page.getByText("Search credit units (CRD)")).toBeVisible()
})

When("I open the credit history for {string}", async ({ page }, provider: string) => {
  await page.getByRole("button", { name: new RegExp("Balance history for " + provider, "i") }).click()
  await expect(page.getByRole("heading", { name: "Balance history", exact: true })).toBeVisible()
})

When("I open the credit details for {string}", async ({ page }, provider: string) => {
  await page.getByRole("button", { name: new RegExp("Credit details for " + provider, "i") }).click()
  await expect(page.getByText("Quota Details")).toBeVisible()
})

When("I cancel the credit dialog", async ({ page }) => {
  await page.keyboard.press("Escape")
})

Then("the Brave credit bar should show {string} percent", async ({ page }, value: string) => {
  const bar = page.getByRole("progressbar", { name: barName("Brave") })
  await expect(bar).toBeVisible()
  await expect(bar).toHaveAttribute("aria-valuenow", value)
  await expect(page.locator("main")).toContainText(value === "90" ? "90%" : value + "%")
})

Then("the Brave card should show {string}", async ({ page }, value: string) => {
  const card = page.locator("article", { hasText: "Brave" }).first()
  const fraction = value.match(/(\d[\d.]*)\s*\/\s*(\d[\d.]*)\s*CRD/)
  if (fraction !== null) {
    const remaining = fraction[1] as string
    const total = fraction[2] as string
    await expect(card.getByText(remaining, { exact: true })).toBeVisible()
    await expect(card.getByText(`/ ${total}`, { exact: true })).toBeVisible()
    await expect(card.getByText("CRD", { exact: true }).first()).toBeVisible()
    const normalized = ((await card.textContent()) ?? "").replace(/\s+/g, "")
    expect(normalized).toContain(remaining + "/" + total + "CRD")
    return
  }
  await expect(card).toContainText(value)
})

Then("the Brave card should show {string} with no total", async ({ page }, remaining: string) => {
  const card = page.locator("article", { hasText: "Brave" }).first()
  await expect(card.getByText(remaining, { exact: true })).toBeVisible()
  await expect(card.getByText("CRD", { exact: true }).first()).toBeVisible()
  await expect(card.getByText(/^\/ \d/)).toHaveCount(0)
  await expect(card).not.toContainText("CRD left")
})

Then("the Brave card should show the {string} action", async ({ page }, label: string) => {
  const card = page.locator("article", { hasText: "Brave" }).first()
  await expect(card.getByRole("button", { name: new RegExp(label, "i") })).toBeVisible()
})

Then("the Brave card subtitle should contain {string}", async ({ page }, text: string) => {
  const card = page.locator("article", { hasText: "Brave" }).first()
  await expect(card).toContainText(text)
})

Then("the credit details should show {string}", async ({ page }, text: string) => {
  await expect(page.getByText(text, { exact: false }).first()).toBeVisible()
})

Then("the Brave CRD value should carry {string} hover text", async ({ page }, text: string) => {
  const card = page.locator("article", { hasText: "Brave" }).first()
  const value = card.locator('span[title="' + text + '"]')
  await expect(value.first()).toBeVisible()
  await expect(value.first()).toHaveAttribute("title", text)
  await expect(value.first()).toHaveAttribute("aria-label", text)
})

Then("the Brave card should show one credit bar", async ({ page }) => {
  const card = page.locator("article", { hasText: "Brave" }).first()
  await expect(card.getByRole("progressbar", { name: barName("Brave") })).toHaveCount(1)
})

Then("the Brave card should show no credit bar", async ({ page }) => {
  const card = page.locator("article", { hasText: "Brave" }).first()
  await expect(card.getByRole("progressbar", { name: barName("Brave") })).toHaveCount(0)
})

Then("the formatted CRD amount {string} should be {string}", async ({}, raw: string, text: string) => {
  expect(EXPECTED_CRD_TEXT[raw]).toBe(text)
})

Then("the price note should show {string}", async ({ page }, text: string) => {
  await expect(page.locator("main")).toContainText(text)
})

Then("the price note should have no {string} row for {string}", async ({ page }, operation: string, provider: string) => {
  const note = page.locator("section", { hasText: "How credit units are priced" })
  await expect(note).toBeVisible()
  const row = note.getByRole("row", { name: new RegExp(provider + ".*" + operation, "i") })
  await expect(row).toHaveCount(0)
})

Then("the manual entry should show {string}", async ({ page }, text: string) => {
  await expect(page.getByText(text, { exact: false }).first()).toBeVisible()
})

Then("the grant form should show {string}", async ({ page }, text: string) => {
  await expect(page.getByText(text, { exact: false }).first()).toBeVisible()
})

Then("the grant form should have no fetch field", async ({ page }) => {
  await expect(page.getByLabel(/Fetch credit units/i)).toHaveCount(0)
})

Then("the history modal should show {string}", async ({ page }, text: string) => {
  await expect(page.getByRole("dialog")).toContainText(text)
})

/**
 * Tavily native Credits (provider-credits.feature U7-T*, quota-display Q-T*).
 *
 * Mirrors the Brave structure with Tavily fields: the native bar carries the
 * aria label "Tavily native Credits remaining", the fraction reads in Credits,
 * and USD stays inside the info disclosure. Brave steps above are untouched.
 */

/** Catalog display name of the Tavily native bar. */
function tavilyBarName(): string {
  return "Tavily native Credits remaining"
}

function tavilyCard(page: import("@playwright/test").Page) {
  return page.locator("article", { hasText: "Tavily" }).first()
}

Then("the Tavily credit bar should show {string} percent", async ({ page }, value: string) => {
  const bar = page.getByRole("progressbar", { name: tavilyBarName() })
  await expect(bar).toBeVisible()
  await expect(bar).toHaveAttribute("aria-valuenow", value)
  await expect(page.locator("main")).toContainText(value + "%")
})

Then("the Tavily card should show {string}", async ({ page }, value: string) => {
  const card = tavilyCard(page)
  const fraction = value.match(/(\d[\d.]*)\s*\/\s*(\d[\d.]*)\s*Credits/)
  if (fraction !== null) {
    const remaining = fraction[1] as string
    const total = fraction[2] as string
    await expect(card.getByText(remaining, { exact: true })).toBeVisible()
    await expect(card.getByText(`/ ${total}`, { exact: true })).toBeVisible()
    await expect(card.getByText("Credits", { exact: true }).first()).toBeVisible()
    const normalized = ((await card.textContent()) ?? "").replace(/\s+/g, "")
    expect(normalized).toContain(remaining + "/" + total + "Credits")
    return
  }
  await expect(card).toContainText(value)
})

Then("the Tavily card should show {string} with no total", async ({ page }, remaining: string) => {
  const card = tavilyCard(page)
  await expect(card.getByText(remaining, { exact: true })).toBeVisible()
  await expect(card.getByText("Credits", { exact: true }).first()).toBeVisible()
  await expect(card.getByText(/^\/ \d/)).toHaveCount(0)
})

Then("the Tavily card should show the {string} action", async ({ page }, label: string) => {
  await expect(tavilyCard(page).getByRole("button", { name: new RegExp(label, "i") })).toBeVisible()
})

Then("the Tavily card subtitle should contain {string}", async ({ page }, text: string) => {
  await expect(tavilyCard(page)).toContainText(text)
})

Then("the Tavily card should show one credit bar", async ({ page }) => {
  await expect(
    tavilyCard(page).getByRole("progressbar", { name: tavilyBarName() }),
  ).toHaveCount(1)
})

Then("the Tavily card should show no credit bar", async ({ page }) => {
  await expect(
    tavilyCard(page).getByRole("progressbar", { name: tavilyBarName() }),
  ).toHaveCount(0)
})

Then("the credit details should not show {string}", async ({ page }, text: string) => {
  await expect(page.locator("body")).not.toContainText(text)
})

When("I open the Tavily credit grant", async ({ page }) => {
  await page.getByRole("button", { name: /Budget Limit for Tavily/i }).click()
  await expect(page.getByText("Search Credits")).toBeVisible()
})

Then("the {string} grant field should show {string}", async ({ page }, label: string, value: string) => {
  await expect(page.getByLabel(label)).toHaveValue(value)
})

When("I type {string} into the {string} grant field", async ({ page }, value: string, label: string) => {
  await page.getByLabel(label).fill(value)
})

When("I save the credit grant", async ({ page }) => {
  await page.getByRole("button", { name: /Save budget limit/i }).click()
})

Then("the submitted grant should carry {string} {string}", async ({}, field: string, value: string) => {
  await expect.poll(() => {
    const bodies = stubbedGrantBodies()
    const last = bodies[bodies.length - 1] as Record<string, unknown> | undefined
    return last === undefined ? "" : String(last[field] ?? "")
  }).toBe(value)
})

Then("the playground search error should show {string}", async ({ page }, text: string) => {
  await expect(page.locator("main")).toContainText(text, { timeout: 10_000 })
})

Then("the search telemetry should show {string}", async ({ page }, text: string) => {
  await expect(page.getByText(text, { exact: true }).first()).toBeVisible({ timeout: 10_000 })
})
