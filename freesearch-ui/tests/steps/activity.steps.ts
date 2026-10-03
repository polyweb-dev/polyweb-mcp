import { expect } from "@playwright/test"
import { Given, When, Then } from "./fixtures"
import { traceListRequests } from "./backendStub"

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
  "the trace detail should show result {string} with title {string}",
  async ({ page }, url: string, title: string) => {
    const dialog = page.getByRole("dialog")
    await expect(dialog.getByText("Results returned", { exact: true })).toBeVisible()
    await expect(dialog.getByText(title, { exact: true })).toBeVisible()
    await expect(dialog.getByText(url, { exact: true })).toBeVisible()
  }
)

Then(
  "the trace detail summary should show status {string} and provider {string}",
  async ({ page }, status: string, provider: string) => {
    const dialog = page.getByRole("dialog")
    await expect(dialog.getByText("Status", { exact: true })).toBeVisible()
    await expect(dialog.getByText(status, { exact: true })).toBeVisible()
    await expect(dialog.getByText(provider, { exact: true })).toBeVisible()
  }
)

Then("the trace detail should show an error {string}", async ({ page }, error: string) => {
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText(error)
})

Then("the trace detail should show no recorded results", async ({ page }) => {
  await expect(page.getByRole("dialog")).toContainText("No results were recorded")
})

Then("the trace detail should show the fetched url {string}", async ({ page }, url: string) => {
  const dialog = page.getByRole("dialog")
  await expect(dialog.getByText("URL fetched", { exact: true })).toBeVisible()
  await expect(dialog).toContainText(url)
})

Then(
  "the stage timeline should list {int} stages with durations",
  async ({ page }, count: number) => {
    const timeline = page.getByRole("list", { name: "Stage timeline" })
    await expect(timeline.getByRole("listitem")).toHaveCount(count)
    for (const item of await timeline.getByRole("listitem").all()) {
      await expect(item).toContainText(/\d+ms/)
    }
  }
)

Then(
  "the stage timeline should mark a failed stage with {string}",
  async ({ page }, error: string) => {
    const timeline = page.getByRole("list", { name: "Stage timeline" })
    await expect(timeline).toContainText(error)
  }
)

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
