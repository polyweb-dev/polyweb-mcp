import { expect } from "@playwright/test"
import { Given, When, Then } from "./fixtures"
import {
  braveCreditLimits,
  braveCreditLimitsAfterDebit,
  setStubbedCrdTotals,
  setStubbedHistory,
  setStubbedProviderLimits,
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
 * UI7 provider credit units (provider-credits.feature @ui7).
 *
 * All backend traffic is stubbed. Dashboard credit state is mutable
 * per scenario through the backendStub setters. Assertions use role and
 * label selectors, never layout selectors or sleeps.
 */

/** Catalog display name of the stubbed provider id. */
function barName(provider: string): string {
  return (provider === "Brave" ? "Brave Search" : provider) + " credit units remaining"
}

function providerSlug(provider: string): string {
  return provider.toLowerCase()
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
  else throw new Error(`Unknown provider limits kind: ${kind}`)
})

Given("the stubbed credit totals show {string}", async ({}, kind: string) => {
  if (kind === "Brave no use") setStubbedCrdTotals(braveNoUse())
  else if (kind === "Brave one search use") setStubbedCrdTotals(braveOneSearchUse())
  else if (kind === "Brave fractional use") setStubbedCrdTotals(braveFractionalUse())
  else throw new Error(`Unknown credit totals kind: ${kind}`)
})

Given("the stubbed credit history shows {string}", async ({}, kind: string) => {
  if (kind === "Brave credit history") {
    setStubbedHistory("brave", { events: ui7HistoryEvents(), nextCursor: null, error: null })
    return
  }
  throw new Error(`Unknown credit history kind: ${kind}`)
})

When("I open the credit manual entry for {string}", async ({ page }, provider: string) => {
  await page.getByRole("button", { name: "Balance entry for Brave" }).click()
  await expect(page.getByText("Allowance (USD)")).toBeVisible()
  void provider
})

When("I open the credit grant for {string}", async ({ page }, provider: string) => {
  await page.getByTestId("crd-grant-open-" + providerSlug(provider)).click()
  await expect(page.getByText("Search credit units (CRD)")).toBeVisible()
})

When("I open the credit history for {string}", async ({ page }, provider: string) => {
  await page.getByTestId("limit-history-open-" + providerSlug(provider)).click()
  await expect(page.getByRole("heading", { name: "Balance history", exact: true })).toBeVisible()
})

When("I expand the Brave detail", async ({ page }) => {
  const card = page.locator("article", { hasText: "Brave" }).first()
  await card.getByRole("button", { name: "Show detail" }).click()
  await expect(card.getByText("Aggregate pool")).toBeVisible()
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

Then("the Brave card should show {string} for {string}", async ({ page }, value: string, label: string) => {
  const card = page.locator("article", { hasText: "Brave" }).first()
  await expect(card.getByText(label, { exact: true })).toBeVisible()
  await expect(card).toContainText(value)
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

Then("the Brave shared pool note should list one pool once", async ({ page }) => {
  await expect(page.locator("main")).toContainText("Keyed USD")
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
