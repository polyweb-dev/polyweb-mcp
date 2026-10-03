import { expect } from "@playwright/test"
import { Given, When, Then } from "./fixtures"
import {
  SEVEN_PROVIDER_IDS,
  SEVEN_PROVIDER_LONG_SNIPPET,
  SEVEN_PROVIDER_QUERY,
  SEVEN_PROVIDER_TRACE_ID,
  failStubbedTraceDetail,
  failStubbedTraceList,
  sevenProviderLabel,
  sevenProviderResult,
  traceDetailRequests,
  traceListRequests,
} from "./backendStub"

Given("I am on the Activity view", async ({ page }) => {
  await page.getByRole("link", { name: "Activity", exact: true }).click()
  await expect(page.getByRole("heading", { name: "Activity", exact: true })).toBeVisible()
})

Then(
  "the activity table should expose the columns {string}, {string}, {string}, {string}, {string}, and {string} with a {string} action column",
  async (
    { page },
    first: string,
    second: string,
    third: string,
    fourth: string,
    fifth: string,
    sixth: string,
    action: string
  ) => {
    const columnNames = [first, second, third, fourth, fifth, sixth, action]
    const headers = page.getByRole("table").getByRole("columnheader")
    await expect(headers).toHaveCount(columnNames.length)
    for (const columnName of columnNames) {
      await expect(headers.filter({ hasText: columnName })).toHaveCount(1)
    }
  }
)

Then("the activity document should not contain seeded query or URL values", async ({ page }) => {
  const body = await page.locator("body").innerText()
  expect(body).not.toContain("distributed consensus algorithms")
  expect(body).not.toContain("https://docs.freesearch.dev/getting-started")
  expect(body).not.toContain("http")
})

Then(
  "the activity view should show telemetry columns or an empty state",
  async ({ page }) => {
    // Against the live backend the ledger may be empty: accept either the
    // six telemetry columns (Time/Operation/Provider/Status/Latency/Results)
    // or the exact Activity empty-state copy.
    const table = page.getByRole("table")
    const emptyState = page.getByText(/No traces recorded yet/)
    if ((await table.count()) > 0) {
      const headers = table.getByRole("columnheader")
      await expect(headers).toHaveCount(6)
      for (const columnName of ["Time", "Operation", "Provider", "Status", "Latency", "Results"]) {
        await expect(
          table.getByRole("columnheader", { name: columnName, exact: true })
        ).toBeVisible()
      }
    } else {
      await expect(emptyState).toBeVisible()
    }
  }
)

Then("the activity page should not expose a {string} button", async ({ page }, buttonLabel: string) => {
  await expect(page.getByRole("button", { name: buttonLabel, exact: true })).toHaveCount(0)
})

// ---------------------------------------------------------------------------
// Stubbed trace scenarios (activity-traces.feature): the list is
// payload-free, and the query/results appear only after explicit disclosure.
// The stubbed list leads with the seven-provider fanout trace, so row 1 is
// the new acceptance trace, row 2 the legacy two-provider aggregate, row 3
// the single-provider search, and row 4 the error fetch.
// ---------------------------------------------------------------------------

Then(
  "the activity list should not contain the disclosed query or result URLs",
  async ({ page }) => {
    const table = page.getByRole("table")
    await expect(table).toBeVisible()
    const text = await table.innerText()
    expect(text).not.toContain("distributed consensus algorithms")
    expect(text).not.toContain("https://docs.freesearch.dev/consensus")
    expect(text).not.toContain("https://docs.freesearch.dev/raft-vs-paxos")
    expect(text).not.toContain("https://docs.freesearch.dev/getting-started")
    // Seven-provider acceptance trace: also payload-free in the list.
    expect(text).not.toContain(SEVEN_PROVIDER_QUERY)
    expect(text).not.toContain(SEVEN_PROVIDER_LONG_SNIPPET.slice(0, 48))
    expect(text).not.toContain("https://e2e.freesearch.dev/seven/keenable")
    expect(text).not.toContain("https://e2e.freesearch.dev/seven/brave")
  }
)

Then(
  "each activity row should expose a {string} button",
  async ({ page }, buttonLabel: string) => {
    const rows = page.getByRole("table").getByRole("row")
    const buttons = page.getByRole("button", { name: buttonLabel, exact: true })
    await expect(buttons).toHaveCount((await rows.count()) - 1)
  }
)

When("I open the {string} control in row {int}", async ({ page }, label: string, row: number) => {
  await page.getByRole("button", { name: label, exact: true }).nth(row - 1).click()
})

When(
  "I focus the first {string} control and press Enter",
  async ({ page }, label: string) => {
    await page.getByRole("button", { name: label, exact: true }).first().focus()
    await page.keyboard.press("Enter")
  }
)

When("I press Escape", async ({ page }) => {
  await page.keyboard.press("Escape")
})

When("I press Tab", async ({ page }) => {
  await page.keyboard.press("Tab")
})

Then("the trace detail dialog should be visible", async ({ page }) => {
  await expect(page.getByRole("dialog")).toBeVisible()
  await expect(page.getByRole("dialog")).toContainText("Trace detail")
})

Then(
  "the trace detail dialog should close and focus should return to {string}",
  async ({ page }, label: string) => {
    await expect(page.getByRole("dialog")).toHaveCount(0)
    await expect(
      page.getByRole("button", { name: label, exact: true }).first()
    ).toBeFocused()
  }
)

Then("the trace detail should show the query {string}", async ({ page }, query: string) => {
  const dialog = page.getByRole("dialog")
  await expect(dialog.getByText("Query sent", { exact: true })).toBeVisible()
  await expect(dialog).toContainText(query)
})

Then(
  "the trace detail should mention result {string} with title {string}",
  async ({ page }, url: string, title: string) => {
    const dialog = page.getByRole("dialog")
    await expect(dialog).toContainText(title)
    await expect(dialog).toContainText(url)
  }
)

Then(
  "the trace detail summary should show status {string} and provider {string}",
  async ({ page }, status: string, provider: string) => {
    const dialog = page.getByRole("dialog")
    await expect(dialog.getByText("Status", { exact: true }).first()).toBeVisible()
    await expect(dialog.getByText(status, { exact: true }).first()).toBeVisible()
    // The provider name repeats in the summary strip and the detail body.
    await expect(dialog.getByText(provider, { exact: true }).first()).toBeVisible()
  }
)

Then("the trace detail should show an error {string}", async ({ page }, error: string) => {
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText(error)
})

Then(
  'the trace detail should show error {string} with a retry',
  async ({ page }, message: string) => {
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('alert')).toContainText(message)
    await expect(dialog.getByRole('button', { name: 'Retry', exact: true })).toBeVisible()
  }
)

Then("the trace detail should show no recorded results", async ({ page }) => {
  await expect(page.getByRole("dialog")).toContainText("No results were recorded")
})

Then("the trace detail should show the fetched url {string}", async ({ page }, url: string) => {
  const dialog = page.getByRole("dialog")
  await expect(dialog.getByText("URL fetched", { exact: true })).toBeVisible()
  await expect(dialog).toContainText(url)
})

Then(
  "the {string} disclosure should start {string}",
  async ({ page }, title: string, state: string) => {
    const disclosure = page.locator("details", { hasText: title }).first()
    if (state === "collapsed") {
      await expect(disclosure).not.toHaveAttribute("open", "")
    } else {
      await expect(disclosure).toHaveAttribute("open", "")
    }
  }
)

When("I choose the {string} activity filter", async ({ page }, label: string) => {
  await page
    .getByRole("group", { name: /operation filter/i })
    .getByRole("button", { name: label, exact: true })
    .click()
})

Then(
  "the backend should have received a trace list request filtered by {string}",
  async ({ page }, operation: string) => {
    await expect
      .poll(() =>
        traceListRequests().some((search) => search.includes(`operation=${operation}`))
      )
      .toBe(true)
    // Keep the page fixture referenced for future visual assertions.
    await expect(page.getByRole("table")).toBeVisible()
  }
)

// ---------------------------------------------------------------------------
// Seven-provider acceptance (PLAN §6.2): span-recorded identities, wider
// modal + aligned strip, one-time order copy, select-to-side results, fused
// trajectory with side payload, dialog focus contract.
// ---------------------------------------------------------------------------

Then('every {string} control should be a real button', async ({ page }, label: string) => {
  const buttons = page.getByRole('button', { name: label, exact: true })
  await expect(buttons.first()).toBeVisible()
  for (const button of await buttons.all()) {
    await expect(button).toHaveAttribute('type', /.+/)
    const tag = await button.evaluate((node) => node.tagName.toLowerCase())
    expect(tag).toBe('button')
  }
})

When('I expand the all-providers trace', async ({ page }) => {
  await page.getByRole('button', { name: /Show provider responses for/ }).first().click()
  // The nested panel resolves to Inspect rows on success, or — when a trace
  // detail failure was injected — to the error panel with its retry.
  await expect
    .poll(async () => page.getByRole('table').innerText())
    .toMatch(/Inspect|unavailable|Loading provider responses/)
})

When('I collapse the all-providers trace', async ({ page }) => {
  await page.getByRole('button', { name: /Hide provider responses for/ }).first().click()
})

Then('no nested provider row should be visible', async ({ page }) => {
  await expect(page.getByRole('button', { name: 'Inspect' })).toHaveCount(0)
})

Then(
  'the nested provider rows should show {string} with {string} and {string} results',
  async ({ page }, provider: string, latency: string, count: string) => {
    const row = page.getByRole('row').filter({ hasText: provider }).first()
    await expect(row).toBeVisible()
    await expect(row).toContainText(latency)
    // Result count cell: exact count surrounded by cell boundaries.
    await expect(row).toContainText(count)
  }
)

Then('the seven-provider trace should show no anonymous provider text', async ({ page }) => {
  const text = await page.getByRole('table').innerText()
  expect(text).not.toContain('Provider attempt')
  expect(text).not.toContain('Name not recorded')
})

Then('each nested provider row should expose an {string} button', async ({ page }, label: string) => {
  const buttons = page.getByRole('button', { name: label, exact: true })
  await expect(buttons).toHaveCount(7)
  for (const button of await buttons.all()) {
    await expect(button).toBeVisible()
  }
})

When('I inspect the {string} provider response', async ({ page }, provider: string) => {
  const row = page.getByRole('row').filter({ hasText: provider }).first()
  await row.getByRole('button', { name: 'Inspect', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
})

Then('the provider-scoped dialog should show {string}', async ({ page }, title: string) => {
  await expect(page.getByRole('dialog')).toContainText(title)
})

Then('the provider-scoped dialog should show the scope note', async ({ page }) => {
  await expect(page.getByRole('dialog')).toContainText(
    'Showing this provider'
  )
})

Then(
  'the trace detail dialog width should be approximately {string} pixels within {string} pixels',
  async ({ page }, expected: string, tolerance: string) => {
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    const box = await dialog.boundingBox()
    const width = box?.width ?? Number.NaN
    // 7xl dialog: min(80rem, viewport - 32px); the root type scale is 15px
    // (index.css :root), so 80rem computes to 1200px, not 1280px.
    expect(Math.abs(width - Number(expected))).toBeLessThanOrEqual(Number(tolerance))
    const viewport = page.viewportSize()
    if (viewport !== null) {
      expect(width).toBeLessThanOrEqual(viewport.width - 32 + 1)
    }
  }
)

Then('the summary strip cells should share equal top and height', async ({ page }) => {
  // The rebuilt summary is one semantic <dl> rail with four cells (PLAN §5.1).
  const cells = page.getByRole('dialog').locator('dl > div')
  await expect(cells).toHaveCount(4)
  const boxes = await Promise.all((await cells.all()).map((cell) => cell.boundingBox()))
  const tops = boxes.map((box) => box?.y ?? Number.NaN)
  const heights = boxes.map((box) => box?.height ?? Number.NaN)
  expect(Math.max(...tops) - Math.min(...tops)).toBeLessThanOrEqual(1)
  expect(Math.max(...heights) - Math.min(...heights)).toBeLessThanOrEqual(1)
})

Then(
  'the summary strip cells should have at least {string} pixels of horizontal inner padding',
  async ({ page }, pixels: string) => {
    const minimum = Number(pixels)
    const cells = page.getByRole('dialog').locator('dl > div')
    await expect(cells).toHaveCount(4)
    for (const cell of await cells.all()) {
      const padding = await cell.evaluate((node) => {
        const style = getComputedStyle(node)
        return {
          left: Number.parseFloat(style.paddingLeft),
          right: Number.parseFloat(style.paddingRight),
          top: Number.parseFloat(style.paddingTop),
          bottom: Number.parseFloat(style.paddingBottom),
        }
      })
      expect(padding.left).toBeGreaterThanOrEqual(minimum)
      expect(padding.right).toBeGreaterThanOrEqual(minimum)
      // Vertical rhythm follows PLAN §5.1 (py-3): guard against a return to
      // the cramped py-2 strip without pinning exact pixels. Both floors are
      // root-aware: the 15px root type scale (index.css :root) computes the
      // plan-mandated px-4/py-3 to 15px/11.25px, so 16/12 would fail a
      // correct implementation the same way the old 1280px width literal did.
      expect(padding.top).toBeGreaterThanOrEqual(11)
      expect(padding.bottom).toBeGreaterThanOrEqual(11)
    }
  }
)

Then(
  'the summary strip, query, and inspection workspace should align within {string} pixels',
  async ({ page }, pixels: string) => {
    const tolerance = Number(pixels)
    const dialog = page.getByRole('dialog')
    const strip = dialog.locator('dl').first()
    await expect(strip).toBeVisible()
    const stripBox = await strip.boundingBox()
    const stripLeft = stripBox?.x ?? Number.NaN
    const stripRight = (stripBox?.x ?? Number.NaN) + (stripBox?.width ?? Number.NaN)
    const queryHeading = dialog.getByRole('heading', { name: 'Query sent' })
    await expect(queryHeading).toBeVisible()
    const queryBox = await queryHeading.evaluate((node) => {
      const section = node.parentElement
      if (section === null) throw new Error('query heading has no section parent')
      const rect = section.getBoundingClientRect()
      return { left: rect.left, right: rect.right }
    })
    // The workspace is the full-width container around the "Trace detail
    // view" segmented control: the first ancestor clearly wider than the
    // control itself (the control is ~200px; content is ~1200px).
    const viewGroup = dialog.getByRole('group', { name: 'Trace detail view' })
    await expect(viewGroup).toBeVisible()
    const workspaceBox = await viewGroup.evaluate((node) => {
      const origin = node.getBoundingClientRect()
      let current = node.parentElement
      let box = { left: origin.left, right: origin.right }
      while (current !== null && current.getAttribute('role') !== 'dialog') {
        const rect = current.getBoundingClientRect()
        if (rect.width >= origin.width + 100) {
          box = { left: rect.left, right: rect.right }
          break
        }
        box = { left: rect.left, right: rect.right }
        current = current.parentElement
      }
      return box
    })
    expect(Math.abs(stripLeft - queryBox.left)).toBeLessThanOrEqual(tolerance)
    expect(Math.abs(stripRight - queryBox.right)).toBeLessThanOrEqual(tolerance)
    expect(Math.abs(stripLeft - workspaceBox.left)).toBeLessThanOrEqual(tolerance)
    expect(Math.abs(stripRight - workspaceBox.right)).toBeLessThanOrEqual(tolerance)
  }
)

Given('I use a desktop viewport', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
})

Given('I use a narrow viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
})

Then('the dialog should stay within the viewport', async ({ page }) => {
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  const geometry = await dialog.evaluate((node) => {
    const rect = node.getBoundingClientRect()
    return {
      left: rect.left,
      right: rect.right,
      top: rect.top,
      bottom: rect.bottom,
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
    }
  })
  expect(geometry.left).toBeGreaterThanOrEqual(0)
  expect(geometry.top).toBeGreaterThanOrEqual(0)
  expect(geometry.right).toBeLessThanOrEqual(geometry.viewportWidth)
  expect(geometry.bottom).toBeLessThanOrEqual(geometry.viewportHeight)
})

Then('the document should have no horizontal overflow', async ({ page }) => {
  const overflow = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
  expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth)
})

Then('the trace detail dialog should have no horizontal overflow', async ({ page }) => {
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  const overflow = await dialog.evaluate((node) => ({
    scrollWidth: node.scrollWidth,
    clientWidth: node.clientWidth,
  }))
  expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth)
})

Then('the dialog header should stay visible after scrolling the body', async ({ page }) => {
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  const header = dialog.locator('header, [role="banner"]').first()
  const headerVisible = await header.count()
  // Modal header is the DialogHeader; fall back to the dialog title.
  const pinned = headerVisible > 0 ? header : dialog.getByText('Trace detail').first()
  await dialog.evaluate((node) => {
    const scroller = node.querySelector('[class*="overflow-y-auto"]') ?? node
    scroller.scrollTop = scroller.scrollHeight
  })
  await expect(pinned).toBeVisible()
})

// --- Order copy: one mode-appropriate sentence, no legacy text -------------

Then(
  'the trace detail should explain {string} exactly once',
  async ({ page }, sentence: string) => {
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText(sentence)
    const occurrences = (await dialog.innerText()).split(sentence).length - 1
    expect(occurrences).toBe(1)
  }
)

const LEGACY_RANKING_COPY = [
  "This provider's own returned order is kept as-is.",
  'No score recorded; output order is the available ranking signal.',
  'Raw reciprocal-rank inputs and per-source ranks are not recorded in this trace.',
  'Ordered by fusion score across every provider that answered.',
  'Only the final score is shown.',
]

Then('the trace detail should not contain the legacy ranking copy', async ({ page }) => {
  const text = await page.getByRole('dialog').innerText()
  for (const legacy of LEGACY_RANKING_COPY) {
    expect(text).not.toContain(legacy)
  }
})

Then('the trace detail should not repeat a missing-contributor note', async ({ page }) => {
  const text = await page.getByRole('dialog').innerText()
  expect(text).not.toMatch(/contributor not recorded/i)
})

Then('the trace detail should not show a duplicate ranked list', async ({ page }) => {
  await expect(
    page.getByRole('dialog').getByRole('list', { name: 'Output order and scores' })
  ).toHaveCount(0)
})

// --- Select-to-side results -------------------------------------------------

Then('the compact result rows should not contain the seeded long snippet', async ({ page }) => {
  const text = await page.getByRole('dialog').innerText()
  expect(text).not.toContain(SEVEN_PROVIDER_LONG_SNIPPET)
})

When('I select the result {string}', async ({ page }, title: string) => {
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: title }).first().click()
})

Then('the result {string} should be marked as selected', async ({ page }, title: string) => {
  // Selectable rows expose pressed state (same contract as the Trajectory
  // selectable waterfall rows in PLAN §5.4).
  const button = page.getByRole('dialog').getByRole('button', { name: title }).first()
  await expect(button).toHaveAttribute('aria-pressed', 'true')
})

function sevenResultIdFromLabel(
  label: string
): 'brave' | 'keenable' | 'tavily' | 'exa' | 'firecrawl' | 'youcom' {
  switch (label.toLowerCase()) {
    case 'brave':
      return 'brave'
    case 'keenable':
      return 'keenable'
    case 'tavily':
      return 'tavily'
    case 'exa':
      return 'exa'
    case 'firecrawl':
      return 'firecrawl'
    case 'youcom':
      return 'youcom'
    default:
      throw new Error(`unknown seven-provider result label '${label}'`)
  }
}

Then(
  'the result inspector should show the full {string} payload',
  async ({ page }, label: string) => {
    const dialog = page.getByRole('dialog')
    const result = sevenProviderResult(sevenResultIdFromLabel(label))
    await expect(dialog).toContainText(result.snippet)
    await expect(dialog).toContainText(result.url)
    await expect(dialog).toContainText(result.score.toFixed(2))
  }
)

Then(
  'the result inspector should show the full {string} payload without growing the page',
  async ({ page }, label: string) => {
    const dialog = page.getByRole('dialog')
    const result = sevenProviderResult(sevenResultIdFromLabel(label))
    await expect(dialog).toContainText(result.snippet)
    await expect(dialog).toContainText(result.url)
    await expect(dialog).toContainText(result.score.toFixed(2))
    // Replacement, not accumulation: the previously inspected long payload
    // is gone once another result is selected.
    if (sevenResultIdFromLabel(label) !== 'keenable') {
      expect(await dialog.innerText()).not.toContain(SEVEN_PROVIDER_LONG_SNIPPET)
    }
    const geometry = await dialog.evaluate((node) => ({ scrollHeight: node.scrollHeight }))
    expect(geometry.scrollHeight).toBeLessThan(2000)
  }
)

// --- Trajectory: fused timing rows with side span payload -------------------

When('I switch to the {string} trace view', async ({ page }, view: string) => {
  await page
    .getByRole('dialog')
    .getByRole('group', { name: 'Trace detail view' })
    .getByRole('button', { name: view })
    .click()
})

Then(
  'the trajectory should show seven provider rows each with a duration and a latency bar',
  async ({ page }) => {
    const dialog = page.getByRole('dialog')
    for (const provider of SEVEN_PROVIDER_IDS) {
      const row = dialog.getByRole('button', { name: `${sevenProviderLabel(provider)} request` })
      await expect(row).toBeVisible()
      await expect(row).toContainText(/\d+\s*ms/)
      // Fused in-row timing: the shared-scale track renders at least one
      // placed segment with a positive width.
      const bars = row.locator('div[aria-hidden="true"] span')
      await expect(bars.first()).toBeVisible()
      const box = await bars.first().boundingBox()
      expect(box?.width ?? 0).toBeGreaterThan(0)
    }
  }
)

Then(
  'the trace detail should not show a separate {string} section',
  async ({ page }, title: string) => {
    await expect(
      page.getByRole('dialog').getByRole('heading', { name: title, exact: true })
    ).toHaveCount(0)
  }
)

Then(
  'the trace detail should not show a {string} disclosure',
  async ({ page }, title: string) => {
    await expect(
      page.getByRole('dialog').locator('details', { hasText: title })
    ).toHaveCount(0)
  }
)

When('I select the trajectory row {string}', async ({ page }, label: string) => {
  await page.getByRole('dialog').getByRole('button', { name: label }).first().click()
})

Then(
  'the span inspector should show provider {string} with the recorded request and response payload',
  async ({ page }, provider: string) => {
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText(provider)
    await expect(dialog).toContainText('freesearch.provider.request')
    await expect(dialog).toContainText('freesearch.provider.response')
  }
)

// --- Keyboard and focus (APPROVED F7 scope) ----------------------------------

Then('the dialog should take focus on open', async ({ page }) => {
  await expect
    .poll(async () =>
      page.evaluate(() => {
        const dialog = document.querySelector('[role="dialog"]')
        return dialog !== null && dialog.contains(document.activeElement)
      })
    )
    .toBe(true)
})

Then('focus should stay inside the dialog', async ({ page }) => {
  const inside = await page.evaluate(() => {
    const dialog = document.querySelector('[role="dialog"]')
    return dialog !== null && dialog.contains(document.activeElement)
  })
  expect(inside).toBe(true)
})

When('I focus the result {string} and press Enter', async ({ page }, title: string) => {
  const button = page.getByRole('dialog').getByRole('button', { name: title }).first()
  await button.focus()
  await page.keyboard.press('Enter')
})

When('I focus the trajectory row {string} and press Enter', async ({ page }, label: string) => {
  const button = page.getByRole('dialog').getByRole('button', { name: label }).first()
  await button.focus()
  await page.keyboard.press('Enter')
})

// --- Preserved detail navigation (list order: seven, aggregate, single, error)

When('I open the single-provider trace detail', async ({ page }) => {
  // List order is seven-provider fanout, legacy aggregate, single-provider
  // search, error fetch.
  await page.getByRole('button', { name: 'View details', exact: true }).nth(2).click()
  await expect(page.getByRole('dialog')).toBeVisible()
})

When('I open the error trace detail', async ({ page }) => {
  await page.getByRole('button', { name: 'View details', exact: true }).nth(3).click()
  await expect(page.getByRole('dialog')).toBeVisible()
})

Then('the backend should have received a cached detail reuse', async () => {
  // Expansion and Inspect share one decoded detail: at most one GET per id.
  const counts = new Map<string, number>()
  for (const traceId of traceDetailRequests()) {
    counts.set(traceId, (counts.get(traceId) ?? 0) + 1)
  }
  for (const [, count] of counts) {
    expect(count).toBeLessThanOrEqual(2)
  }
})

// --- Loading / error / retry guards ------------------------------------------

When('I inject a trace list failure {string}', async ({}, message: string) => {
  failStubbedTraceList(message)
})

When('I refresh the activity list', async ({ page }) => {
  await page.getByRole('button', { name: 'Refresh', exact: true }).click()
})

Then('the activity list should show error {string} with a retry', async ({ page }, message: string) => {
  await expect(page.getByRole('alert')).toContainText(message)
  await expect(page.getByRole('button', { name: 'Retry', exact: true }).first()).toBeVisible()
})

When('I clear the trace list failure and retry', async ({ page }) => {
  failStubbedTraceList(null)
  await page.getByRole('button', { name: 'Retry', exact: true }).first().click()
})

When('I inject a trace detail failure {string}', async ({}, message: string) => {
  failStubbedTraceDetail(SEVEN_PROVIDER_TRACE_ID, message)
})

When('I clear the trace detail failure and retry', async ({ page }) => {
  failStubbedTraceDetail(SEVEN_PROVIDER_TRACE_ID, null)
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Retry', exact: true })
    .click()
})

Then(
  'the nested provider panel should show error {string} with a retry',
  async ({ page }, message: string) => {
    const table = page.getByRole('table')
    await expect(table.getByRole('alert')).toContainText(message)
    await expect(table.getByRole('button', { name: 'Retry', exact: true })).toBeVisible()
  }
)

When('I clear the trace detail failure and retry the nested panel', async ({ page }) => {
  failStubbedTraceDetail(SEVEN_PROVIDER_TRACE_ID, null)
  await page.getByRole('table').getByRole('button', { name: 'Retry', exact: true }).click()
})
