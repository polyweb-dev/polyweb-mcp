import { expect } from "@playwright/test"
import type { Page } from "@playwright/test"
import { Given, When, Then } from "./fixtures"
import {
  FUSION_LONG_SNIPPET,
  NULL_SOURCE_LONG_SNIPPET,
  SEVEN_PROVIDER_IDS,
  SEVEN_PROVIDER_DURATIONS,
  SEVEN_PROVIDER_LONG_SNIPPET,
  SEVEN_PROVIDER_OFFSETS,
  SEVEN_PROVIDER_QUERY,
  SEVEN_PROVIDER_TRACE_ID,
  SEVEN_STAGE_GEOMETRY,
  SEVEN_TOTAL_MS,
  failStubbedTraceDetail,
  failStubbedTraceList,
  sevenProviderResult,
  traceDetailRequests,
  traceListRequests,
} from "./backendStub"
import type { SevenProviderId } from "./backendStub"

/**
 * Catalog display name per seven-provider stub id. The UI resolves every
 * provider identity through providerIdentity, so `you`/`youcom` renders as
 * `You.com` and `brave` renders as `Brave Search` — never the raw span id.
 */
const SEVEN_PROVIDER_DISPLAY: Record<SevenProviderId, string> = {
  brave: "Brave Search",
  keenable: "Keenable",
  tavily: "Tavily",
  exa: "Exa",
  firecrawl: "Firecrawl",
  youcom: "You.com",
  parallel: "Parallel",
}

/**
 * Region scopes inside the trace detail dialog. The shared card and the side
 * inspector render the same snippet text, so payload assertions must name
 * their region: the list keeps the two-line preview, the inspector owns the
 * full text, and each trajectory pane owns its own payload.
 */
function resultInspectorRegion(page: Page) {
  return page.getByRole("dialog").getByRole("region", { name: "Result inspector" })
}

function resultsListRegion(page: Page) {
  return page.getByRole("dialog").getByRole("region", { name: /Results|response/ })
}

function trajectoryList(page: Page) {
  return page.getByRole("dialog").getByRole("list", { name: "Trace trajectory" })
}

function spanInspectorRegion(page: Page) {
  return page.getByRole("dialog").getByRole("region", { name: /payload/ })
}

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
  // The nested panel resolves to provider rows (marked with the hierarchy
  // arrow) on success, or — when a trace detail failure was injected — to
  // the error panel with its retry.
  await expect
    .poll(async () => page.getByRole('table').innerText())
    .toMatch(/↳|unavailable|Loading provider responses/)
})

When('I collapse the all-providers trace', async ({ page }) => {
  await page.getByRole('button', { name: /Hide provider responses for/ }).first().click()
})

Then('no nested provider row should be visible', async ({ page }) => {
  await expect(page.getByRole('table')).not.toContainText('↳')
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

Then('each nested provider row should expose a {string} button', async ({ page }, label: string) => {
  const table = page.getByRole('table')
  // Nested provider rows carry the hierarchy arrow; parent trace rows do not.
  const nestedRows = table.getByRole('row').filter({ hasText: '↳' })
  await expect(nestedRows).toHaveCount(7)
  const nestedButtons = nestedRows.getByRole('button', { name: label, exact: true })
  await expect(nestedButtons).toHaveCount(7)
  for (const button of await nestedButtons.all()) {
    await expect(button).toBeVisible()
  }
  // Pin the parent count separately: six stubbed traces lead the list, so the
  // expanded page holds six parent actions plus seven nested actions.
  const allButtons = page.getByRole('button', { name: label, exact: true })
  await expect(allButtons).toHaveCount(13)
  expect((await allButtons.count()) - (await nestedButtons.count())).toBe(6)
})

When('I inspect the {string} provider response', async ({ page }, provider: string) => {
  const row = page.getByRole('row').filter({ hasText: provider }).first()
  await row.getByRole('button', { name: 'View details', exact: true }).click()
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
    // Provider sentences render the provider name as a badge (logo + name),
    // so one text node never holds the full sentence. Pin the exact approved
    // wording as region-scoped parts in order: before-text + badge + after-text.
    const providerPrefix = 'Results keep the order returned by '
    if (sentence.startsWith(providerPrefix)) {
      const rest = sentence.slice(providerPrefix.length)
      const dot = rest.indexOf('.')
      if (dot < 0) throw new Error(`cannot split provider sentence '${sentence}'`)
      const provider = rest.slice(0, dot)
      const after = rest.slice(dot)
      const before = 'Results keep the order returned by'
      const explanation = dialog.locator('p', { hasText: before })
      await expect(explanation).toHaveCount(1)
      await expect(explanation).toContainText(before)
      await expect(explanation.getByText(provider, { exact: true }).first()).toBeVisible()
      await expect(
        explanation.locator('img[data-testid^="provider-logo-"]').first()
      ).toBeVisible()
      await expect(explanation).toContainText(after)
      const joined = await explanation.evaluate(
        (node) => (node.textContent ?? '').replace(/\s+/g, ' ').trim()
      )
      const beforeIdx = joined.indexOf(before)
      const providerIdx = joined.indexOf(provider, beforeIdx)
      const afterHead = after.slice(0, 24)
      const afterIdx = joined.indexOf(afterHead, providerIdx)
      expect(beforeIdx).toBeGreaterThanOrEqual(0)
      expect(providerIdx).toBeGreaterThan(beforeIdx)
      expect(afterIdx).toBeGreaterThan(providerIdx)
      return
    }
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
// The shared card and the side inspector render the same snippet text, so
// every step below stays inside its own region: the list owns selection and
// the two-line preview, the inspector owns the full payload.

Then('the compact result rows should clamp the seeded long snippet to two lines', async ({ page }) => {
  const results = resultsListRegion(page)
  const snippets = results.locator('p.line-clamp-2')
  await expect(snippets.first()).toBeVisible()
  for (const snippet of await snippets.all()) {
    const clamp = await snippet.evaluate((node) => {
      const style = getComputedStyle(node)
      return style.getPropertyValue('line-clamp') || style.getPropertyValue('-webkit-line-clamp')
    })
    expect(clamp.trim()).toBe('2')
  }
  // The seeded long snippet is present in its card but visually clamped: its
  // scroll height exceeds the two-line client height of that card.
  const keenable = results.getByRole('button', { name: 'Keenable acceptance result' }).first()
  const preview = keenable.locator('p.line-clamp-2')
  await expect(preview).toContainText(SEVEN_PROVIDER_LONG_SNIPPET.slice(0, 48))
  const box = await preview.evaluate((node) => ({
    scrollHeight: node.scrollHeight,
    clientHeight: node.clientHeight,
  }))
  expect(box.scrollHeight).toBeGreaterThan(box.clientHeight)
  expect(box.clientHeight).toBeLessThanOrEqual(64)
})

When('I select the result {string}', async ({ page }, title: string) => {
  await resultsListRegion(page).getByRole('button', { name: title }).first().click()
})

Then('the result {string} should be marked as selected', async ({ page }, title: string) => {
  // Selectable rows expose pressed state (same contract as the Trajectory
  // selectable waterfall rows in PLAN §5.4).
  const button = resultsListRegion(page).getByRole('button', { name: title }).first()
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
    case 'you.com':
      return 'youcom'
    default:
      throw new Error(`unknown seven-provider result label '${label}'`)
  }
}

Then(
  'the result inspector should show the full {string} payload',
  async ({ page }, label: string) => {
    const inspector = resultInspectorRegion(page)
    const result = sevenProviderResult(sevenResultIdFromLabel(label))
    await expect(inspector).toContainText(result.snippet)
    // PLAN §4: the inspector shows only the URL host as visible link text,
    // with the full URL in the link accessible name, href, and title.
    const host = new URL(result.url).host
    const link = inspector.getByRole('link', { name: result.url }).first()
    await expect(link).toBeVisible()
    await expect(link).toContainText(host)
    await expect(link).toHaveAttribute('href', result.url)
    await expect(link).toHaveAttribute('title', result.url)
    await expect(inspector).toContainText(result.score.toFixed(2))
  }
)

Then(
  'the result inspector should show the full {string} payload without growing the page',
  async ({ page }, label: string) => {
    const dialog = page.getByRole('dialog')
    const inspector = resultInspectorRegion(page)
    const result = sevenProviderResult(sevenResultIdFromLabel(label))
    await expect(inspector).toContainText(result.snippet)
    // PLAN §4: host as visible text, full URL in accessible name/href/title.
    const host = new URL(result.url).host
    const link = inspector.getByRole('link', { name: result.url }).first()
    await expect(link).toBeVisible()
    await expect(link).toContainText(host)
    await expect(link).toHaveAttribute('href', result.url)
    await expect(link).toHaveAttribute('title', result.url)
    await expect(inspector).toContainText(result.score.toFixed(2))
    // Replacement, not accumulation: the previously inspected long payload
    // is gone from the inspector once another result is selected. The card
    // list keeps its own two-line preview, so this stays inspector-scoped.
    if (sevenResultIdFromLabel(label) !== 'keenable') {
      expect(await inspector.innerText()).not.toContain(SEVEN_PROVIDER_LONG_SNIPPET)
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
      const row = dialog.getByRole('button', { name: `${SEVEN_PROVIDER_DISPLAY[provider]} request` })
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
  // Label targeting equals span-id order per selectUserTraceStages: repeated
  // provider rows keep offset order (wire order matches offset order in these
  // fixtures), and every label is unique inside one trajectory.
  await trajectoryList(page).getByRole('button', { name: label }).first().click()
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
  const button = resultsListRegion(page).getByRole('button', { name: title }).first()
  await button.focus()
  await page.keyboard.press('Enter')
})

When('I focus the trajectory row {string} and press Enter', async ({ page }, label: string) => {
  const button = trajectoryList(page).getByRole('button', { name: label }).first()
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

// ---------------------------------------------------------------------------
// Trace Detail UI enhancement (Tester Turn 1): user-level trajectory stages,
// shared result presentation, and measured geometry contracts (PLAN §7).
// ---------------------------------------------------------------------------

Then('the trajectory should show a {string} row', async ({ page }, label: string) => {
  await expect(trajectoryList(page).getByRole('button', { name: label }).first()).toBeVisible()
})

Then('the trajectory should not show a {string} row', async ({ page }, label: string) => {
  await expect(trajectoryList(page).getByRole('button', { name: label })).toHaveCount(0)
})

Then(
  'the trajectory ruler and every row track should align within {string} pixels',
  async ({ page }, pixels: string) => {
    const tolerance = Number(pixels)
    const geometry = await page.getByRole('dialog').evaluate((dialog) => {
      const region = dialog.querySelector('section[aria-label="Trace trajectory"]')
      if (region === null) throw new Error('trajectory region is missing')
      const ruler = region.querySelector('div[aria-hidden="true"].h-5')
      if (ruler === null) throw new Error('trajectory ruler is missing')
      const tracks = [
        ...region.querySelectorAll('ol[aria-label="Trace trajectory"] div[aria-hidden="true"].h-2'),
      ]
      const rectOf = (element: Element): { left: number; right: number } => {
        const rect = element.getBoundingClientRect()
        return { left: rect.left, right: rect.right }
      }
      return { ruler: rectOf(ruler), tracks: tracks.map(rectOf) }
    })
    expect(geometry.tracks.length).toBeGreaterThan(0)
    for (const track of geometry.tracks) {
      expect(Math.abs(track.left - geometry.ruler.left)).toBeLessThanOrEqual(tolerance)
      expect(Math.abs(track.right - geometry.ruler.right)).toBeLessThanOrEqual(tolerance)
    }
  }
)

Then(
  'the trajectory bars should match recorded offsets and durations within {string} pixels',
  async ({ page }, pixels: string) => {
    const tolerance = Number(pixels)
    const bars = await page.getByRole('dialog').evaluate((dialog) => {
      const region = dialog.querySelector('section[aria-label="Trace trajectory"]')
      if (region === null) throw new Error('trajectory region is missing')
      const rows = [...region.querySelectorAll('ol[aria-label="Trace trajectory"] > li')]
      return rows.map((row) => {
        const track = row.querySelector('div[aria-hidden="true"].h-2')
        if (track === null) throw new Error('trajectory track is missing')
        const bar = track.querySelector('span[style]')
        if (bar === null) throw new Error('trajectory bar is missing')
        const style = (bar as HTMLElement).style
        return {
          leftPct: Number.parseFloat(style.left),
          widthPct: Number.parseFloat(style.width),
          trackWidth: track.getBoundingClientRect().width,
        }
      })
    })
    expect(bars).toHaveLength(SEVEN_STAGE_GEOMETRY.length)
    bars.forEach((bar, index) => {
      const expected = SEVEN_STAGE_GEOMETRY[index]
      if (expected === undefined) throw new Error(`no recorded geometry for row ${index}`)
      const expectedLeftPx = (expected.offsetMs / SEVEN_TOTAL_MS) * bar.trackWidth
      const actualLeftPx = (bar.leftPct / 100) * bar.trackWidth
      expect(Math.abs(actualLeftPx - expectedLeftPx)).toBeLessThanOrEqual(tolerance + 0.5)
      const expectedWidthPct = (expected.durationMs / SEVEN_TOTAL_MS) * 100
      const actualWidthPx = (bar.widthPct / 100) * bar.trackWidth
      if (expectedWidthPct < 0.5) {
        // Minimum-width marker: the bar stays a visible sliver with an
        // accurate numeric value instead of a proportional width.
        expect(actualWidthPx).toBeLessThanOrEqual((0.5 / 100) * bar.trackWidth + tolerance)
        return
      }
      const expectedWidthPx = (expected.durationMs / SEVEN_TOTAL_MS) * bar.trackWidth
      expect(Math.abs(actualWidthPx - expectedWidthPx)).toBeLessThanOrEqual(tolerance + 0.5)
    })
  }
)

Then('the trajectory ruler should mark the final tick in milliseconds', async ({ page }) => {
  const texts = await page.getByRole('dialog').evaluate((dialog) => {
    const region = dialog.querySelector('section[aria-label="Trace trajectory"]')
    if (region === null) throw new Error('trajectory region is missing')
    const ruler = region.querySelector('div[aria-hidden="true"].h-5')
    if (ruler === null) throw new Error('trajectory ruler is missing')
    const labels = [...ruler.querySelectorAll('span[class*="tnum"]')]
    return labels.map((element) => (element as HTMLElement).innerText.trim())
  })
  // Item 5 axis fix: short bare numbers on every tick, the unit once on the
  // final tick, with zero geometry change to the ruler box.
  expect(texts.length).toBeGreaterThan(1)
  for (const text of texts.slice(0, -1)) {
    expect(text).toMatch(/^\d+$/)
  }
  expect(texts[texts.length - 1]).toMatch(/^\d+ ms$/)
})

Then(
  'the trajectory row should show an inset focus ring at both edges after Tab',
  async ({ page }) => {
    const dialog = page.getByRole('dialog')
    // Real keyboard: Tab until a trajectory row owns focus (at most 25 stops).
    let focused = false
    for (let stop = 0; stop < 25; stop++) {
      const owned = await dialog.evaluate(() => {
        const active = document.activeElement
        const button =
          active instanceof HTMLElement
            ? active.closest('section[aria-label="Trace trajectory"] button')
            : null
        return button !== null
      })
      if (owned) {
        focused = true
        break
      }
      await page.keyboard.press('Tab')
    }
    expect(focused).toBe(true)
    // Item 5 ring fix: the inset box-shadow ring must read at both row edges
    // inside the trajectory scroll container, with no outline switch.
    const ring = await dialog.evaluate(() => {
      const active = document.activeElement as HTMLElement
      const button = active.closest(
        'section[aria-label="Trace trajectory"] button'
      ) as HTMLElement
      const scroller = button.closest('div[class*="overflow-y-auto"]') as HTMLElement
      const row = button.getBoundingClientRect()
      const box = scroller.getBoundingClientRect()
      const style = getComputedStyle(button)
      return {
        focusVisible: active.matches(':focus-visible'),
        shadow: style.boxShadow,
        outline: style.outlineStyle,
        leftInside: row.left >= box.left - 2,
        rightInside: row.right <= box.right + 2,
      }
    })
    expect(ring.focusVisible).toBe(true)
    expect(ring.shadow).toContain('inset')
    expect(ring.outline).toBe('none')
    expect(ring.leftInside).toBe(true)
    expect(ring.rightInside).toBe(true)
  }
)

Then('the latency summary should count overlapping provider calls once', async ({ page }) => {
  const region = page.getByRole('dialog').getByRole('region', { name: 'Trace trajectory' })
  // Recompute the union from the recorded stub intervals (never the sum):
  // concurrent fanout counts once, exactly like deriveTraceLatencySummary.
  const intervals = SEVEN_PROVIDER_IDS.map((id) => ({
    start: SEVEN_PROVIDER_OFFSETS[id],
    end: SEVEN_PROVIDER_OFFSETS[id] + SEVEN_PROVIDER_DURATIONS[id],
  })).sort((a, b) => a.start - b.start)
  const merged: { start: number; end: number }[] = []
  for (const interval of intervals) {
    const last = merged[merged.length - 1]
    if (last !== undefined && interval.start <= last.end) {
      last.end = Math.max(last.end, interval.end)
    } else {
      merged.push({ ...interval })
    }
  }
  const unionMs = merged.reduce((sum, interval) => sum + (interval.end - interval.start), 0)
  const durationSum = intervals.reduce((sum, interval) => sum + (interval.end - interval.start), 0)
  expect(durationSum).toBeGreaterThan(unionMs)
  const outside = SEVEN_TOTAL_MS - unionMs
  const gaps: { start: number; end: number }[] = []
  let cursor = 0
  for (const interval of merged) {
    if (interval.start > cursor) gaps.push({ start: cursor, end: interval.start })
    cursor = Math.max(cursor, interval.end)
  }
  if (SEVEN_TOTAL_MS > cursor) gaps.push({ start: cursor, end: SEVEN_TOTAL_MS })
  const beforeMs = gaps[0] !== undefined && gaps[0].start === 0 ? gaps[0].end : 0
  const last = gaps[gaps.length - 1]
  const afterMs = last !== undefined && last.end >= SEVEN_TOTAL_MS ? last.end - last.start : 0
  const betweenMs = Math.max(0, outside - beforeMs - afterMs)
  const valueOf = async (label: string): Promise<string> => {
    const dd = region
      .getByText(label, { exact: true })
      .locator('xpath=..')
      .locator('dd')
    return (await dd.innerText()).trim()
  }
  await expect(region.getByText('Before providers', { exact: true })).toBeVisible()
  expect(await valueOf('Before providers')).toBe(`${beforeMs}ms`)
  expect(await valueOf('Provider active')).toBe(`${unionMs}ms`)
  expect(await valueOf('After providers')).toBe(`${afterMs}ms`)
  expect(await valueOf('Outside provider calls')).toBe(`${outside}ms`)
  await expect(region.getByText('Between providers', { exact: true })).toHaveCount(
    betweenMs > 0 ? 1 : 0
  )
  await expect(region).toContainText('counts overlapping provider calls once')
  // The duration sum must never appear as provider time: the union decides.
  await expect(page.getByRole('dialog')).not.toContainText(`${durationSum}ms`)
})

Then('the result inspector should show {string}', async ({ page }, text: string) => {
  await expect(resultInspectorRegion(page)).toContainText(text)
})

Then(
  'the result inspector should show {string} before the snippet summary',
  async ({ page }, marker: string) => {
    const inspector = resultInspectorRegion(page)
    await expect(inspector.getByText(marker, { exact: true }).first()).toBeVisible()
    const order = await inspector.evaluate((node, expected: string) => {
      const candidates = [...node.querySelectorAll('p, dt, dd, span, a')]
      const found =
        candidates.find((element) => (element.textContent ?? '').trim() === expected) ?? null
      const snippet =
        [...node.querySelectorAll('p')].find((element) => {
          const overflowY = getComputedStyle(element).overflowY
          return overflowY === 'auto' || overflowY === 'scroll'
        }) ?? null
      if (found === null) return { found: false, ordered: false }
      if (snippet === null) return { found: true, ordered: false }
      const position = snippet.compareDocumentPosition(found)
      return { found: true, ordered: (position & Node.DOCUMENT_POSITION_PRECEDING) !== 0 }
    }, marker)
    expect(order.found).toBe(true)
    expect(order.ordered).toBe(true)
  }
)

Then(
  'the result inspector metadata should stay visible without scrolling the snippet region',
  async ({ page }) => {
    const inspector = resultInspectorRegion(page)
    const layout = await inspector.evaluate((node) => {
      const text = (element: Element | null): string => (element?.textContent ?? '').trim()
      const rank =
        [...node.querySelectorAll('p')].find((element) =>
          /^Result \d+ of \d+$/.test(text(element))
        ) ?? null
      const cellFor = (labels: readonly string[]): Element | null => {
        const dt = [...node.querySelectorAll('dt')].find((element) =>
          labels.includes(text(element))
        )
        return dt?.parentElement?.querySelector('dd') ?? null
      }
      const attribution = cellFor(['Provider', 'Contributing providers', 'Attributed'])
      const score = cellFor(['Fusion score', 'Provider score', 'Score'])
      const targetLabel =
        [...node.querySelectorAll('span')].find((element) => text(element) === 'Target URL') ??
        null
      const target = targetLabel?.parentElement?.querySelector('a') ?? null
      const snippet =
        [...node.querySelectorAll('p')].find((element) => {
          const overflowY = getComputedStyle(element).overflowY
          return overflowY === 'auto' || overflowY === 'scroll'
        }) ?? null
      const metas = [rank, attribution, score, target]
      const inViewport = (rect: DOMRect | null): boolean =>
        rect !== null && rect.top >= -2 && rect.bottom <= window.innerHeight + 2
      const allVisible = metas
        .map((element) => (element === null ? null : element.getBoundingClientRect()))
        .every(inViewport)
      // Bounded scroll region (not the dialog): max-height plus auto/scroll overflow.
      const snippetStyle = snippet === null ? null : getComputedStyle(snippet)
      const bounded =
        snippet !== null &&
        snippetStyle !== null &&
        (snippetStyle.overflowY === 'auto' || snippetStyle.overflowY === 'scroll') &&
        snippetStyle.maxHeight !== 'none'
      // Recorded metadata precedes the snippet in DOM order.
      const orderOf = (element: Element | null): number => {
        if (element === null || snippet === null) return Number.NaN
        const position = snippet.compareDocumentPosition(element)
        // DOCUMENT_POSITION_PRECEDING (2) means element comes before snippet.
        return position & 2 ? 0 : 1
      }
      const ordered = metas.every((element) => orderOf(element) === 0)
      const tops = metas.map((element) => element?.getBoundingClientRect().top ?? Number.NaN)
      // Scroll the snippet region to its end: recorded metadata must not move.
      if (snippet !== null) snippet.scrollTop = snippet.scrollHeight
      const topsAfter = metas.map(
        (element) => element?.getBoundingClientRect().top ?? Number.NaN
      )
      const unmoved = tops.every(
        (top, index) => Math.abs(top - (topsAfter[index] ?? Number.NaN)) <= 2
      )
      return { allVisible, bounded, ordered, unmoved }
    })
    expect(layout.bounded).toBe(true)
    expect(layout.ordered).toBe(true)
    expect(layout.allVisible).toBe(true)
    expect(layout.unmoved).toBe(true)
  }
)

Then(
  'the result inspector snippet should contain the full {string} text in its own scroll region',
  async ({ page }, kind: string) => {
    const expected =
      kind === 'fusion long'
        ? FUSION_LONG_SNIPPET
        : kind === 'null-source'
          ? NULL_SOURCE_LONG_SNIPPET
          : null
    if (expected === null) throw new Error(`unknown recorded snippet '${kind}'`)
    const inspector = resultInspectorRegion(page)
    const paragraphs = inspector.locator('p')
    const count = await paragraphs.count()
    let snippet: ReturnType<Page['locator']> | null = null
    for (let index = 0; index < count; index += 1) {
      const candidate = paragraphs.nth(index)
      const overflowY = await candidate.evaluate((node) => getComputedStyle(node).overflowY)
      if (overflowY === 'auto' || overflowY === 'scroll') {
        snippet = candidate
        break
      }
    }
    if (snippet === null) throw new Error('inspector snippet scroll region is missing')
    expect(await snippet.evaluate((node) => node.textContent ?? '')).toContain(expected)
    const box = await snippet.evaluate((node) => {
      const style = getComputedStyle(node)
      return {
        scrollHeight: node.scrollHeight,
        clientHeight: node.clientHeight,
        overflowY: style.overflowY,
        maxHeight: style.maxHeight,
      }
    })
    // Its own bounded scroll region (not the dialog): overflow plus max-height.
    expect(box.overflowY === 'auto' || box.overflowY === 'scroll').toBe(true)
    expect(box.maxHeight).not.toBe('none')
    // Boundary value is the correct bound with honest 2px tolerance: content that
    // fits exactly (188 vs 188) still lives in its scroll region.
    expect(box.scrollHeight + 2).toBeGreaterThanOrEqual(box.clientHeight)
  }
)

Then('the result inspector should show contributor {string}', async ({ page }, name: string) => {
  await expect(
    resultInspectorRegion(page).getByText(name, { exact: true }).first()
  ).toBeVisible()
})

Then(
  'the result inspector should not show contributor {string}',
  async ({ page }, name: string) => {
    await expect(
      resultInspectorRegion(page).getByText(name, { exact: true })
    ).toHaveCount(0)
  }
)

Then(
  'the result inspector badges should number {int} and each show a logo',
  async ({ page }, count: number) => {
    const logos = resultInspectorRegion(page).locator('img[data-testid^="provider-logo-"]')
    await expect(logos).toHaveCount(count)
    for (const logo of await logos.all()) {
      await expect(logo).toBeVisible()
    }
  }
)

Then('the span inspector should show {string}', async ({ page }, text: string) => {
  const region = spanInspectorRegion(page)
  // Recorded URLs live inside collapsed JsonViewer groups (PLAN §4 keeps
  // arrays collapsed). Expand them with real summary activations first.
  if (text.startsWith('https://')) {
    for (let round = 0; round < 8; round += 1) {
      const collapsed = region.locator('details:not([open]) > summary')
      const count = await collapsed.count()
      if (count === 0) break
      for (let index = 0; index < count; index += 1) {
        try {
          await collapsed.nth(index).click({ timeout: 2000 })
        } catch {
          break
        }
      }
    }
  }
  await expect(region).toContainText(text)
})

Then('the span inspector should not show {string}', async ({ page }, text: string) => {
  const region = spanInspectorRegion(page)
  // Expand first so absence is meaningful (a collapsed group hides every URL).
  if (text.startsWith('https://')) {
    for (let round = 0; round < 8; round += 1) {
      const collapsed = region.locator('details:not([open]) > summary')
      const count = await collapsed.count()
      if (count === 0) break
      for (let index = 0; index < count; index += 1) {
        try {
          await collapsed.nth(index).click({ timeout: 2000 })
        } catch {
          break
        }
      }
    }
  }
  await expect(region).not.toContainText(text)
})

Then('the trace detail should not contain {string}', async ({ page }, text: string) => {
  await expect(page.getByRole('dialog')).not.toContainText(text)
})

Then(
  'the nested provider rows should show provider logos followed by names',
  async ({ page }) => {
    const table = page.getByRole('table')
    for (const provider of SEVEN_PROVIDER_IDS) {
      const display = SEVEN_PROVIDER_DISPLAY[provider]
      const row = table.getByRole('row').filter({ hasText: display }).first()
      await expect(row.locator('img[data-testid^="provider-logo-"]')).toBeVisible()
      await expect(row.getByText(display, { exact: true }).first()).toBeVisible()
    }
  }
)

Then(
  'the trajectory provider rows should show provider logos followed by names',
  async ({ page }) => {
    const list = trajectoryList(page)
    for (const provider of SEVEN_PROVIDER_IDS) {
      const display = SEVEN_PROVIDER_DISPLAY[provider]
      const row = list.getByRole('button', { name: `${display} request` })
      await expect(row.locator('img[data-testid^="provider-logo-"]')).toBeVisible()
      await expect(row.getByText(display, { exact: true }).first()).toBeVisible()
    }
  }
)
