import { expect } from "@playwright/test"
import type { Page } from "@playwright/test"
import { Given, When, Then } from "./fixtures"
import { holdStubbedSearches, releaseHeldSearches } from "./backendStub"

/**
 * Playground persistence acceptance (PLAN §4.3): drafts/results/loading/error
 * survive page switches without refetching and survive reloads via the
 * project-scoped localStorage key (polyweb:playground:v2:<account>:<project>).
 * All backend traffic stays stubbed (@stub); request counts prove
 * navigation/rehydration never re-issues /search|/fetch.
 *
 * Step-text uniqueness: every pattern here is new — submission, tab, sidebar,
 * heading, direct-navigation, and reload phrasings are reused from
 * playground.steps.ts / tab-unification.steps.ts / workspace.steps.ts /
 * url-routing.steps.ts and are not redefined.
 */

/** Every playground key: the project-scoped v2 keys and any legacy v1 key. */
const PERSIST_PREFIX = "polyweb:playground:"

interface RequestCounts {
  search: number
  fetch: number
  searchBaseline: number | null
}

const countsByPage = new WeakMap<Page, RequestCounts>()
const attachedPages = new WeakSet<Page>()

function countsOf(page: Page): RequestCounts {
  let counts = countsByPage.get(page)
  if (!counts) {
    counts = { search: 0, fetch: 0, searchBaseline: null }
    countsByPage.set(page, counts)
  }
  return counts
}

function pathnameOf(url: string): string | null {
  try {
    return new URL(url).pathname
  } catch {
    return null
  }
}

function attachRequestCounter(page: Page): void {
  if (attachedPages.has(page)) return
  attachedPages.add(page)
  countsByPage.set(page, { search: 0, fetch: 0, searchBaseline: null })
  page.on("request", (request) => {
    if (request.method() !== "POST") return
    const pathname = pathnameOf(request.url())
    if (pathname === null) return
    const counts = countsOf(page)
    if (pathname === "/search") counts.search += 1
    else if (pathname === "/fetch") counts.fetch += 1
  })
}

Given("the persisted playground state is cleared", async ({ page }) => {
  attachRequestCounter(page)
  await page.evaluate((prefix) => {
    const keys: string[] = []
    for (let index = 0; index < window.localStorage.length; index += 1) {
      const key = window.localStorage.key(index)
      if (key !== null && key.startsWith(prefix)) keys.push(key)
    }
    for (const key of keys) window.localStorage.removeItem(key)
  }, PERSIST_PREFIX)
})

Then("the persisted search draft should be {string}", async ({ page }, draft: string) => {
  await expect(page.getByPlaceholder(/Search the web/i)).toHaveValue(draft)
})

Then("the persisted search results should show {string}", async ({ page }, text: string) => {
  await expect(page.locator("main").getByText(text).first()).toBeVisible()
})

Then("the persisted fetch URL should be {string}", async ({ page }, url: string) => {
  await expect(page.getByPlaceholder(/URL to fetch/i)).toHaveValue(url)
})

Then("the persisted fetch document should show {string}", async ({ page }, text: string) => {
  await expect(page.locator("main").getByText(text).first()).toBeVisible()
})

Then("the persisted search error should contain {string}", async ({ page }, text: string) => {
  const banner = page.locator("main").locator('p[style*="status-danger"]', { hasText: text })
  await expect(banner.first()).toBeVisible()
})

Then("the playground search button should read {string}", async ({ page }, label: string) => {
  await expect(page.getByRole("button", { name: label, exact: true })).toBeVisible()
})

Then("the persisted search request count should be {int}", async ({ page }, expected: number) => {
  await expect
    .poll(() => countsOf(page).search, { timeout: 10_000 })
    .toBe(expected)
})

Then("the persisted fetch request count should be {int}", async ({ page }, expected: number) => {
  await expect.poll(() => countsOf(page).fetch, { timeout: 10_000 }).toBe(expected)
})

When("I note the persisted search request count", async ({ page }) => {
  countsOf(page).searchBaseline = countsOf(page).search
})

Then("the persisted search request count should not have increased", async ({ page }) => {
  const counts = countsOf(page)
  const baseline = counts.searchBaseline ?? 0
  await expect.poll(() => countsOf(page).search, { timeout: 10_000 }).toBe(baseline)
})

When("I hold the persisted search response", async ({ page }) => {
  attachRequestCounter(page)
  // Hold every search open in the shared stub (project gate and request log
  // stay in force) until the release step.
  holdStubbedSearches(null)
})

When("I release the persisted search response", async ({ page: _page }) => {
  releaseHeldSearches()
})
