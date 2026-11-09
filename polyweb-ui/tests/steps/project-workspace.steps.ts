import { expect } from "@playwright/test"
import type { Locator, Page } from "@playwright/test"
import { Given, Then, When } from "./fixtures"
import {
  DEFAULT_ACCOUNT_EMAIL,
  DEFAULT_ACCOUNT_ID,
  executionTraffic,
  heldSearchCount,
  holdStubbedSearches,
  legacyTraceRequests,
  releaseHeldSearches,
  traceListRequests,
} from "./backendStub"
import {
  BETA_USAGE_EVENTS,
  BETA_USAGE_UNITS,
  GONE_LATENCY_MS,
  METADATA_ONLY_LATENCY_MS,
  RESULTS_NOT_STORED_LATENCY_MS,
  seedDetailCopyTraces,
  seedOlderErrorTraces,
} from "./projectActivityStub"
import {
  installProjectStub,
  isProjectStubInstalled,
  projectStubAccountId,
  projectStubId,
  resetProjectStub,
  setProjectStubAccount,
  setProjectStubRoles,
} from "./projectStub"
import { secondTab } from "./tabs"

/**
 * Project-scoped playground, Activity and Usage (TASK-000047 U2).
 *
 * Playground, Activity and Usage live under `/p/:projectId/...`. Features that
 * keep the default stubbed session (a role-less system administrator) add a
 * project membership with "the stubbed session works in project <name>"; the
 * project routes then come from projectStub.ts while the backend stub keeps
 * serving system access, so system-permission steps still apply. Features
 * on the member session of projects.steps.ts ("the projects backend is
 * stubbed") use the same project routes.
 *
 * Project section segments: "overview" is the project root; "playground",
 * "activity", "usage", "members" and "api-keys" are sub-paths.
 */

const PLAYGROUND_V2_PREFIX = "polyweb:playground:v2"
const PLAYGROUND_V1_PREFIX = "polyweb:playground:v1"
const RAW_KEY_MARKER = "fs_live_"

/**
 * Give the default stubbed session project memberships once per tab: Alpha
 * as a project member (search, fetch, traces, usage, providers), served by
 * the project stub without replacing the backend stub's system access.
 */
async function ensureDefaultProjectWorkspace(page: Page): Promise<void> {
  if (isProjectStubInstalled(page)) return
  resetProjectStub()
  setProjectStubAccount(DEFAULT_ACCOUNT_EMAIL, [], DEFAULT_ACCOUNT_ID)
  await installProjectStub(page, { systemAccess: false })
}

function sectionPath(projectName: string, section: string): string {
  const id = projectStubId(projectName)
  return section === "overview" ? `/p/${id}` : `/p/${id}/${section}`
}

Given("the stubbed session works in project {word}", async ({ page }, name: string) => {
  await ensureDefaultProjectWorkspace(page)
  setProjectStubRoles(name, ["project_member"])
})

When(
  "I open the {string} section of project {word}",
  async ({ page }, section: string, name: string) => {
    await ensureDefaultProjectWorkspace(page)
    await page.goto(sectionPath(name, section))
  }
)

When("I follow the {string} link of the Project navigation", async ({ page }, label: string) => {
  const link = page
    .getByRole("navigation", { name: "Project" })
    .getByRole("link", { name: label, exact: true })
  await expect(link).toBeVisible({ timeout: 15_000 })
  await link.click()
})

Then(
  "the page URL path should be the {string} section of project {word}",
  async ({ page }, section: string, name: string) => {
    const expected = sectionPath(name, section)
    await expect(async () => {
      expect(new URL(page.url()).pathname).toBe(expected)
    }).toPass({ timeout: 10_000 })
  }
)

// --- Playground: project id, human session, browser storage --------------------

function searchInput(page: Page): Locator {
  return page.getByPlaceholder(/Search the web/i)
}

Then(
  "the last search request should name project {word}",
  async ({ page: _page }, name: string) => {
    await expect.poll(() => executionTraffic().filter((r) => r.operation === "search").length).toBeGreaterThan(0)
    const searches = executionTraffic().filter((record) => record.operation === "search")
    const last = searches[searches.length - 1]
    expect(last.body.project_id).toBe(projectStubId(name))
  }
)

Then(
  "the last fetch request should name project {word}",
  async ({ page: _page }, name: string) => {
    await expect.poll(() => executionTraffic().filter((r) => r.operation === "fetch").length).toBeGreaterThan(0)
    const fetches = executionTraffic().filter((record) => record.operation === "fetch")
    const last = fetches[fetches.length - 1]
    expect(last.body.project_id).toBe(projectStubId(name))
  }
)

Then(
  "every search and fetch request should use the human session without an API key",
  async ({ page: _page }) => {
    const records = executionTraffic()
    expect(records.length).toBeGreaterThan(0)
    for (const record of records) {
      const authorization = record.headers.authorization ?? ""
      // The human session: the in-memory access token of the refresh flow.
      expect(authorization).toMatch(/^Bearer \S+$/)
      expect(authorization).not.toContain(RAW_KEY_MARKER)
      expect(record.headers["x-api-key"]).toBeUndefined()
      expect(JSON.stringify(record.headers)).not.toContain(RAW_KEY_MARKER)
      expect(JSON.stringify(record.body)).not.toContain(RAW_KEY_MARKER)
      expect(record.body).not.toHaveProperty("api_key")
    }
  }
)

Then("browser storage should hold no API key", async ({ page }) => {
  const stored = await page.evaluate(() => {
    const values: string[] = []
    for (const storage of [window.localStorage, window.sessionStorage]) {
      for (let index = 0; index < storage.length; index += 1) {
        const key = storage.key(index) ?? ""
        values.push(key, storage.getItem(key) ?? "")
      }
    }
    return values.join("\n")
  })
  expect(stored).not.toContain(RAW_KEY_MARKER)
  expect(page.url()).not.toContain(RAW_KEY_MARKER)
})

async function persistedPlaygroundKeys(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const keys: string[] = []
    for (let index = 0; index < window.localStorage.length; index += 1) {
      const key = window.localStorage.key(index)
      if (key !== null && key.startsWith("polyweb:playground:")) keys.push(key)
    }
    return keys.sort()
  })
}

Then(
  "the playground state should be persisted only under the project key of {word}",
  async ({ page }, name: string) => {
    const expected = `${PLAYGROUND_V2_PREFIX}:${projectStubAccountId()}:${projectStubId(name)}`
    await expect.poll(() => persistedPlaygroundKeys(page)).toEqual([expected])
    expect((await persistedPlaygroundKeys(page)).some((key) => key.startsWith(PLAYGROUND_V1_PREFIX))).toBe(false)
  }
)

Then(
  "the persisted playground state of project {word} should contain {string}",
  async ({ page }, name: string, draft: string) => {
    const key = `${PLAYGROUND_V2_PREFIX}:${projectStubAccountId()}:${projectStubId(name)}`
    await expect
      .poll(() => page.evaluate((k) => window.localStorage.getItem(k) ?? "", key))
      .toContain(draft)
  }
)

Then("the playground should show the result {string}", async ({ page }, title: string) => {
  await expect(page.locator("main").getByText(title, { exact: true }).first()).toBeVisible({
    timeout: 15_000,
  })
})

Then("the playground should not show the result {string}", async ({ page }, title: string) => {
  await expect(page.locator("main").getByText(title, { exact: false })).toHaveCount(0)
})

Then("the playground should show no search results", async ({ page }) => {
  await expect(page.getByRole("heading", { name: "Playground", exact: true })).toBeVisible({
    timeout: 15_000,
  })
  await expect(page.locator("main").getByText(/% match/i)).toHaveCount(0)
  await expect(page.locator("main").getByText(/isolation result/i)).toHaveCount(0)
})

Then("the playground search draft should be {string}", async ({ page }, draft: string) => {
  await expect(searchInput(page)).toHaveValue(draft, { timeout: 15_000 })
})

When(
  "I type {string} into the playground search of the second tab",
  async ({ page: _page }, draft: string) => {
    await searchInput(secondTab()).fill(draft)
  }
)

Then(
  "the playground search draft of the second tab should be {string}",
  async ({ page: _page }, draft: string) => {
    await expect(searchInput(secondTab())).toHaveValue(draft, { timeout: 15_000 })
  }
)

When(
  "I submit the playground search query {string} in the second tab",
  async ({ page: _page }, query: string) => {
    const tab = secondTab()
    await searchInput(tab).fill(query)
    await tab.getByRole("button", { name: "Search", exact: true }).click()
  }
)

Then("the second tab should show the result {string}", async ({ page: _page }, title: string) => {
  await expect(secondTab().locator("main").getByText(title, { exact: true }).first()).toBeVisible({
    timeout: 15_000,
  })
})

Then(
  "the second tab should not show the result {string}",
  async ({ page: _page }, title: string) => {
    await expect(secondTab().locator("main").getByText(title, { exact: false })).toHaveCount(0)
  }
)

When("I reload both tabs", async ({ page }) => {
  await page.reload()
  await secondTab().reload()
})

// --- Playground: project switch while a slow search is in flight ---------------

/** Browser-side failures (e.g. net::ERR_ABORTED) of search requests, per tab. */
const failedSearches = new WeakMap<Page, string[]>()

Given("searches for {string} respond slowly", async ({ page }, query: string) => {
  holdStubbedSearches(query)
  const failures: string[] = []
  failedSearches.set(page, failures)
  page.on("requestfailed", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname === "/search") {
      failures.push(request.failure()?.errorText ?? "failed")
    }
  })
})

Then("the slow search request should have been cancelled", async ({ page }) => {
  // The contract: a project switch aborts the in-flight request (the
  // runner's AbortController), observed as a browser-side request failure.
  await expect.poll(() => failedSearches.get(page)?.length ?? 0, { timeout: 10_000 }).toBeGreaterThan(0)
  console.log(`[project-playground] slow Alpha search failure: ${failedSearches.get(page)?.join(", ")}`)
})

Then("the slow search should be in flight", async ({ page }) => {
  await expect.poll(() => heldSearchCount(), { timeout: 15_000 }).toBe(1)
  await expect(page.getByRole("button", { name: "Executing...", exact: true })).toBeVisible()
})

When("the slow search response arrives", async ({ page: _page }) => {
  releaseHeldSearches()
  // Settled means answered or aborted by the browser; either way the late
  // Alpha result is now in the client's hands (or was cancelled).
  await expect
    .poll(() => {
      const searches = executionTraffic().filter((r) => r.operation === "search")
      return searches.length > 0 && searches.every((r) => r.outcome !== "pending")
    })
    .toBe(true)
  const outcomes = executionTraffic()
    .filter((r) => r.operation === "search")
    .map((r) => r.outcome)
  console.log(`[project-playground] slow Alpha search outcome: ${outcomes.join(", ")}`)
})

// --- Activity: filters, Load more and retention after detail close --------------

Given(
  "project {word} holds {int} older failed fetch traces",
  async ({ page }, name: string, count: number) => {
    await ensureDefaultProjectWorkspace(page)
    seedOlderErrorTraces(projectStubId(name), count)
  }
)

Given(
  "project {word} recorded a metadata-only, a results-not-stored and a pruned trace",
  async ({ page }, name: string) => {
    await ensureDefaultProjectWorkspace(page)
    seedDetailCopyTraces(projectStubId(name))
  }
)

/** The Activity filter control named `name`: a group of buttons or a select. */
function activityFilter(page: Page, name: string): Locator {
  const pattern = new RegExp(name, "i")
  const main = page.locator("main")
  return main
    .getByRole("group", { name: pattern })
    .or(main.getByRole("radiogroup", { name: pattern }))
    .or(main.getByRole("combobox", { name: pattern }))
    .first()
}

When(
  "I set the Activity {string} filter to {string}",
  async ({ page }, name: string, option: string) => {
    const control = activityFilter(page, name)
    await expect(control).toBeVisible({ timeout: 15_000 })
    const role = await control.getAttribute("role")
    const tag = await control.evaluate((node) => node.tagName.toLowerCase())
    if (tag === "select") {
      await control.selectOption({ label: option })
      return
    }
    if (role === "combobox") {
      await control.click()
      await page.getByRole("option", { name: option, exact: true }).click()
      return
    }
    await control
      .getByRole(role === "radiogroup" ? "radio" : "button", { name: option, exact: true })
      .click()
  }
)

Then(
  "the Activity {string} filter should show {string}",
  async ({ page }, name: string, option: string) => {
    const control = activityFilter(page, name)
    await expect(control).toBeVisible({ timeout: 15_000 })
    const role = await control.getAttribute("role")
    const tag = await control.evaluate((node) => node.tagName.toLowerCase())
    if (tag === "select") {
      await expect(control.locator("option:checked")).toHaveText(option)
      return
    }
    if (role === "combobox") {
      await expect(control).toContainText(option)
      return
    }
    if (role === "radiogroup") {
      await expect(control.getByRole("radio", { name: option, exact: true })).toBeChecked()
      return
    }
    await expect(control.getByRole("button", { name: option, exact: true })).toHaveAttribute(
      "aria-pressed",
      "true"
    )
  }
)

Then("the Activity URL query should be {string}", async ({ page }, expected: string) => {
  const want = [...new URLSearchParams(expected).entries()].sort()
  await expect(async () => {
    const url = new URL(page.url())
    expect(url.pathname).toMatch(/^\/p\/[0-9a-f-]{36}\/activity$/)
    expect([...url.searchParams.entries()].sort()).toEqual(want)
  }).toPass({ timeout: 10_000 })
})

function listedTraceButtons(page: Page): Locator {
  return page.getByRole("table").getByRole("button", { name: "View details", exact: true })
}

Then("the Activity list should show {int} traces", async ({ page }, count: number) => {
  await expect(listedTraceButtons(page)).toHaveCount(count, { timeout: 15_000 })
})

Then(
  "every listed trace should have the outcome {string}",
  async ({ page }, outcome: string) => {
    const rows = page.getByRole("table").getByRole("row").filter({
      has: page.getByRole("button", { name: "View details", exact: true }),
    })
    const texts = await rows.allInnerTexts()
    expect(texts.length).toBeGreaterThan(0)
    for (const text of texts) expect(text).toContain(outcome)
  }
)

When("I load more traces", async ({ page }) => {
  await page.getByRole("button", { name: "Load more", exact: true }).click()
})

Then("the Activity list should offer {string}", async ({ page }, label: string) => {
  await expect(page.getByRole("button", { name: label, exact: true })).toBeVisible({
    timeout: 15_000,
  })
})

Then("the Activity list should not offer {string}", async ({ page }, label: string) => {
  await expect(page.getByRole("button", { name: label, exact: true })).toHaveCount(0)
})

Then(
  "the backend should have received a project trace list request with {string}",
  async ({ page: _page }, fragment: string) => {
    const parts = fragment.split("&")
    await expect
      .poll(() =>
        traceListRequests().some((search) => {
          const params = new URLSearchParams(search)
          return parts.every((part) => {
            const [key, value] = part.split("=")
            return value === "*" ? params.has(key) : params.get(key) === value
          })
        })
      )
      .toBe(true)
  }
)

Then("the removed global trace read should not have been called", async ({ page: _page }) => {
  expect(legacyTraceRequests()).toEqual([])
})

When("I close the trace detail dialog", async ({ page }) => {
  await expect(page.getByRole("dialog")).toBeVisible()
  await page.keyboard.press("Escape")
  await expect(page.getByRole("dialog")).toHaveCount(0)
})

const SEEDED_LATENCY: Record<string, number> = {
  "metadata-only": METADATA_ONLY_LATENCY_MS,
  "results-not-stored": RESULTS_NOT_STORED_LATENCY_MS,
  pruned: GONE_LATENCY_MS,
}

When("I open the detail of the {word} trace", async ({ page }, kind: string) => {
  const latency = SEEDED_LATENCY[kind]
  if (latency === undefined) throw new Error(`unknown seeded trace kind ${kind}`)
  const row = page
    .getByRole("table")
    .getByRole("row")
    .filter({ has: page.getByRole("cell", { name: new RegExp(`^${latency}\\s?ms$`) }) })
    .first()
  await expect(row).toBeVisible({ timeout: 15_000 })
  await row.getByRole("button", { name: "View details", exact: true }).click()
  await expect(page.getByRole("dialog")).toBeVisible()
})

Then("the trace detail should say {string}", async ({ page }, copy: string) => {
  await expect(page.getByRole("dialog")).toContainText(copy, { timeout: 15_000 })
})

Then("the trace detail opens in Summary", async ({ page }) => {
  const views = page.getByRole("dialog").getByRole("group", { name: "Trace detail views" })
  await expect(views.getByRole("button", { name: "Summary" })).toHaveAttribute("aria-pressed", "true")
})

Then("the trace detail should not say {string}", async ({ page }, copy: string) => {
  await expect(page.getByRole("dialog")).not.toContainText(copy)
})

// --- Usage ---------------------------------------------------------------------

function usageTable(page: Page, name: string): Locator {
  return page.getByRole("table", { name, exact: true })
}

Then(
  "the {string} table should have the columns {string}",
  async ({ page }, name: string, list: string) => {
    const columns = list.split(",").map((column) => column.trim())
    const headers = usageTable(page, name).getByRole("columnheader")
    await expect(headers).toHaveCount(columns.length, { timeout: 15_000 })
    for (const [index, column] of columns.entries()) {
      await expect(headers.nth(index)).toHaveText(column)
    }
  }
)

Then(
  "the {string} table should show a {string} {string} row",
  async ({ page }, name: string, provider: string, operation: string) => {
    const row = usageTable(page, name)
      .getByRole("row")
      .filter({ hasText: new RegExp(provider, "i") })
      .filter({ hasText: new RegExp(operation, "i") })
    await expect(row.first()).toBeVisible({ timeout: 15_000 })
  }
)

Then(
  "the {string} table should show {string} in the {string} row",
  async ({ page }, name: string, value: string, provider: string) => {
    const row = usageTable(page, name)
      .getByRole("row")
      .filter({ hasText: new RegExp(provider, "i") })
      .first()
    await expect(row).toContainText(value, { timeout: 15_000 })
  }
)

Then(
  "the {string} table should not show a {string} row",
  async ({ page }, name: string, provider: string) => {
    const table = usageTable(page, name)
    await expect(table).toBeVisible({ timeout: 15_000 })
    await expect(table.getByRole("cell", { name: new RegExp(provider, "i") })).toHaveCount(0)
  }
)

Then("no usage table should show the usage of project Beta", async ({ page }) => {
  for (const name of ["Usage totals"]) {
    const table = usageTable(page, name)
    await expect(table).toBeVisible()
    await expect(table.getByRole("cell", { name: /^exa$/i })).toHaveCount(0)
    await expect(table).not.toContainText(BETA_USAGE_UNITS)
    await expect(table.getByRole("cell", { name: String(BETA_USAGE_EVENTS), exact: true })).toHaveCount(0)
  }
})
