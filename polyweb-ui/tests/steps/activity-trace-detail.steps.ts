import { expect } from "@playwright/test"
import type { Page } from "@playwright/test"
import { Given, When, Then } from "./fixtures"
import { traceDetailRequests, traceListRequests } from "./backendStub"
import { projectStubId } from "./projectStub"
import { seedVaultPool } from "./vaultStub"
import { SUCCESS_TRACE_ID } from "../../src/test/fixtures/activity"

/**
 * Playground parity for the shared result presentation (Tester Turn 1,
 * PLAN §7): the Activity trace detail converges toward this presentation, so
 * the stubbed Playground pins it — shared card, shared inspector,
 * non-selectable waterfall, View details trace popup, and fetch metadata.
 *
 * Step-text uniqueness: every pattern here is new. Navigation, provider
 * pinning, search/fetch submission, and playground tab phrasings reuse
 * workspace.steps.ts, playground.steps.ts, and tab-unification.steps.ts and
 * are not redefined. Browser fixtures stay in fixtures.ts.
 */

function playgroundMain(page: Page) {
  return page.locator("main")
}

function returnedResultsRegion(page: Page) {
  return playgroundMain(page).getByRole("region", { name: "Returned results" })
}

function playgroundInspectorRegion(page: Page) {
  return playgroundMain(page).getByRole("region", {
    name: "Result inspector and execution waterfall",
  })
}

Given("project {word} has a {string} pool for search", async ({}, name: string, provider: string) => {
  // The routing-order stub lists pooled providers plus keyless Keenable, so
  // pinning a keyed provider in the Playground needs a project pool first.
  seedVaultPool(provider, projectStubId(name), ["search"])
})

Then(
  "the playground cards should show titles, urls, two-line snippets, and scores",
  async ({ page }) => {
    const results = returnedResultsRegion(page)
    // The stub serves two fixed Brave hits; the mapped cards keep their
    // titles, full URLs, snippets, and percentage scores.
    await expect(results.getByText("Live backend result one")).toBeVisible()
    await expect(results.getByText("https://example.com/one")).toBeVisible()
    await expect(results.getByText("First live snippet.")).toBeVisible()
    await expect(results.getByText("Live backend result two")).toBeVisible()
    await expect(results.getByText("https://example.com/two")).toBeVisible()
    await expect(results.getByText("Second live snippet.")).toBeVisible()
    // One provider answered, so the cards carry no per-result badge; the
    // telemetry bar names the provider once.
    await expect(results.getByText("Brave Search", { exact: true })).toHaveCount(0)
    await expect(playgroundMain(page)).toContainText(/Resolved by\s*Brave Search/)
    await expect(results.getByText("92% match")).toBeVisible()
    // The second hit recorded no score (null): the shared ResultScore shows
    // nothing rather than inventing "0% match".
    const second = results.getByRole("button", { name: /Live backend result two/ }).first()
    await expect(second).toBeVisible()
    await expect(second).not.toContainText("% match")
    await expect(results.getByText("0% match")).toHaveCount(0)
    await expect(results.getByText("Sep 5, 2026")).toBeVisible()
    // Two-line preview: one clamped snippet paragraph per card.
    await expect(results.locator("p.line-clamp-2")).toHaveCount(2)
  }
)

Then(
  "each playground card should keep fetch and external-link actions outside selection",
  async ({ page }) => {
    const results = returnedResultsRegion(page)
    const selectors = results.locator('button[aria-pressed]')
    await expect(selectors).toHaveCount(2)
    for (const selector of await selectors.all()) {
      // No nested controls inside the selection button: fetch and external
      // link stay siblings with their own targets and never select the card.
      await expect(selector.locator("button, a")).toHaveCount(0)
    }
    const fetchButtons = results.locator('button[data-testid^="fetch-result-"]')
    await expect(fetchButtons).toHaveCount(2)
    for (const fetch of await fetchButtons.all()) {
      await expect(fetch).toBeVisible()
    }
    const externalLinks = results.locator('a[title="Open external link"]')
    await expect(externalLinks).toHaveCount(2)
    await expect(externalLinks.first()).toHaveAttribute("href", "https://example.com/one")
  }
)

When("I select the playground result {string}", async ({ page }, title: string) => {
  await returnedResultsRegion(page).getByRole("button", { name: title }).first().click()
})

Then(
  "the playground inspector should show the shared result presentation",
  async ({ page }) => {
    const inspector = playgroundInspectorRegion(page)
    await expect(inspector.getByText("Provider", { exact: true })).toBeVisible()
    await expect(inspector.getByText("Brave Search", { exact: true }).first()).toBeVisible()
    await expect(
      inspector.locator('img[data-testid="provider-logo-brave"]').first()
    ).toBeVisible()
    await expect(inspector.getByText("Score", { exact: true })).toBeVisible()
    await expect(inspector.getByText("92% match")).toBeVisible()
    await expect(inspector.getByText("Target URL", { exact: true })).toBeVisible()
    await expect(inspector.getByText("example.com", { exact: true })).toBeVisible()
    await expect(inspector.getByText("Snippet summary", { exact: true })).toBeVisible()
    await expect(inspector).toContainText("First live snippet.")
  }
)

Then(
  "the playground inspector link should carry the Open target URL tooltip",
  async ({ page }) => {
    const inspector = playgroundInspectorRegion(page)
    // The shared inspector shows the host text with the full URL behind the
    // link target, its title, and its accessible name (Item 1 tooltip fix).
    const link = inspector.locator('a[title="Open target URL"]').first()
    await expect(link).toBeVisible()
    await expect(link).toHaveAttribute("href", "https://example.com/one")
    await expect(link).toHaveAttribute("title", "Open target URL")
  }
)

Then(
  "the playground waterfall should be non-selectable with latency and result counts",
  async ({ page }) => {
    const inspector = playgroundInspectorRegion(page)
    await expect(inspector.getByText("Execution waterfall", { exact: true })).toBeVisible()
    const list = inspector.getByRole("list", { name: "Provider latency waterfall" })
    await expect(list.getByText("Brave Search", { exact: true }).first()).toBeVisible()
    await expect(list).toContainText(/187\s?ms/)
    await expect(list).toContainText("2 res")
    // Non-selectable lanes: the shared renderer without onSelect renders no buttons.
    await expect(list.getByRole("button")).toHaveCount(0)
    await expect(list.locator('img[data-testid="provider-logo-brave"]')).toBeVisible()
  }
)

Then("the playground should offer View details instead of raw JSON", async ({ page }) => {
  const main = playgroundMain(page)
  await expect(main.getByRole("button", { name: "View details", exact: true })).toBeVisible()
  await expect(main.getByRole("button", { name: /raw JSON/i })).toHaveCount(0)
  await expect(main.getByRole("group", { name: "Raw search response" })).toHaveCount(0)
})

When("I open the playground View details", async ({ page }) => {
  await playgroundMain(page).getByRole("button", { name: "View details", exact: true }).click()
})

Then("the playground trace detail popup should show the project trace", async ({ page }) => {
  // The stubbed search names Alpha's success trace in X-Trace-Id; the popup
  // reads it through the project trace route and shows the Activity inspector.
  const dialog = page.getByRole("dialog", { name: "Trace detail" })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText("distributed consensus algorithms").first()).toBeVisible()
  await expect(dialog.getByText("Consensus algorithms explained").first()).toBeVisible()
  expect(traceDetailRequests()).toContain(SUCCESS_TRACE_ID)
  expect(traceListRequests()).toEqual([])
})

When("I close the playground trace detail popup", async ({ page }) => {
  await page.getByRole("dialog", { name: "Trace detail" }).getByRole("button", { name: "Close" }).click()
  await expect(page.getByRole("dialog", { name: "Trace detail" })).toHaveCount(0)
})

Then("the playground results should still show {string}", async ({ page }, title: string) => {
  await expect(returnedResultsRegion(page).getByText(title)).toBeVisible()
})

Then(
  "the playground fetch result should show metadata, provider badge, and copy action",
  async ({ page }) => {
    const main = playgroundMain(page)
    await expect(main.getByText("Document metadata", { exact: true })).toBeVisible()
    await expect(main.getByText("Live document title")).toBeVisible()
    await expect(main).toContainText("https://example.com/parity-doc")
    // The composer footer labels its picker "Provider" too; the fact row comes last.
    await expect(main.getByText("Provider", { exact: true }).last()).toBeVisible()
    await expect(main.locator('img[data-testid^="provider-logo-"]').first()).toBeVisible()
    await expect(main.getByText("Parsed markdown", { exact: true })).toBeVisible()
    const copy = main.getByRole("button", { name: "Copy markdown", exact: true })
    await expect(copy).toBeVisible()
    await copy.click()
    await expect(main.getByRole("button", { name: "Copied", exact: true })).toBeVisible()
  }
)

Then(
  "the playground fetch result should show the catalog provider name {string}",
  async ({ page }, name: string) => {
    const main = playgroundMain(page)
    // Item 1 name fix: the fetch badge resolves the raw wire value through
    // providerIdentity, so the stubbed Keenable fetch shows its catalog name.
    // Scope to the metadata Provider row: the closed provider combobox also
    // holds an exact-name option that must not satisfy this assertion.
    const providerRow = main.getByText("Provider", { exact: true }).last().locator("xpath=..")
    await expect(providerRow.getByText(name, { exact: true })).toBeVisible()
    const logoKey = name.toLowerCase().replace(/[^a-z]/g, "")
    await expect(
      providerRow.locator(`img[data-testid="provider-logo-${logoKey}"]`)
    ).toBeVisible()
  }
)
