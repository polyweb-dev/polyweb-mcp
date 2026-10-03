import { expect } from "@playwright/test"
import type { Page, Route } from "@playwright/test"
import { Given, When, Then } from "./fixtures"
import { searchResponseFixture } from "../../src/test/backendFixtures"

/**
 * Playground persistence acceptance (PLAN §4.3): drafts/results/loading/error
 * survive page switches without refetching and survive reloads via the
 * namespaced localStorage key. All backend traffic stays stubbed (@stub);
 * request counts prove navigation/rehydration never re-issues /search|/fetch.
 *
 * Step-text uniqueness: every pattern here is new — submission, tab, sidebar,
 * heading, direct-navigation, and reload phrasings are reused from
 * playground.steps.ts / tab-unification.steps.ts / workspace.steps.ts /
 * url-routing.steps.ts and are not redefined.
 */

const PERSIST_KEY = "freesearch:playground:v1"

interface RequestCounts {
  search: number
  fetch: number
  searchBaseline: number | null
}

const countsByPage = new WeakMap<Page, RequestCounts>()
const attachedPages = new WeakSet<Page>()
const heldSearchRoutes = new WeakMap<Page, Route[]>()

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

function readJsonBody(route: Route): Record<string, unknown> {
  try {
    return JSON.parse(route.request().postData() ?? "{}") as Record<string, unknown>
  } catch {
    return {}
  }
}

Given("the persisted playground state is cleared", async ({ page }) => {
  attachRequestCounter(page)
  await page.evaluate((key) => window.localStorage.removeItem(key), PERSIST_KEY)
})

Then("the persisted search draft should be {string}", async ({ page }, draft: string) => {
  await expect(page.getByPlaceholder(/Search across all providers/i)).toHaveValue(draft)
})

Then("the persisted search results should show {string}", async ({ page }, text: string) => {
  await expect(page.locator("main").getByText(text).first()).toBeVisible()
})

Then("the persisted fetch URL should be {string}", async ({ page }, url: string) => {
  await expect(page.getByPlaceholder(/Enter a URL to fetch/i)).toHaveValue(url)
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
  await page.unroute("**/search")
  await page.route("**/search", async (route) => {
    const held = heldSearchRoutes.get(page) ?? []
    held.push(route)
    heldSearchRoutes.set(page, held)
  })
})

When("I release the persisted search response", async ({ page }) => {
  const held = heldSearchRoutes.get(page) ?? []
  heldSearchRoutes.set(page, [])
  for (const route of held) {
    const body = readJsonBody(route)
    const routing = (body.routing ?? {}) as { providers?: unknown }
    const providers = Array.isArray(routing.providers) ? routing.providers : []
    const pinned = typeof providers[0] === "string" ? (providers[0] as string) : "brave"
    const query = typeof body.query === "string" ? (body.query as string) : "stubbed query"
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(searchResponseFixture({ query, provider: pinned })),
    })
  }
  await page.unroute("**/search")
  await page.route("**/search", async (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    const body = readJsonBody(route)
    const routing = (body.routing ?? {}) as { providers?: unknown }
    const providers = Array.isArray(routing.providers) ? routing.providers : []
    const pinned = typeof providers[0] === "string" ? (providers[0] as string) : "brave"
    const query = typeof body.query === "string" ? (body.query as string) : "stubbed query"
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(searchResponseFixture({ query, provider: pinned })),
    })
  })
})
