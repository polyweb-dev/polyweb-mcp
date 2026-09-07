import { expect } from "@playwright/test"
import { Given, When, Then } from "./fixtures"

Given("I am on the Activity view", async ({ page }) => {
  await page.getByRole("button", { name: "Activity", exact: true }).click()
  await expect(page.getByRole("heading", { name: "Activity", exact: true })).toBeVisible()
})

Then(
  "the activity table should expose only the columns {string}, {string}, {string}, {string}, {string}, and {string}",
  async (
    { page },
    first: string,
    second: string,
    third: string,
    fourth: string,
    fifth: string,
    sixth: string
  ) => {
    const columnNames = [first, second, third, fourth, fifth, sixth]
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
    // six telemetry columns (Time/Operation/Provider/Status/Latency/Units)
    // or the exact ActivityStream empty-state copy.
    const table = page.getByRole("table")
    const emptyState = page.getByText(/No events recorded yet/)
    if ((await table.count()) > 0) {
      const headers = table.getByRole("columnheader")
      await expect(headers).toHaveCount(6)
      for (const columnName of ["Time", "Operation", "Provider", "Status", "Latency", "Units"]) {
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
