import { expect } from "@playwright/test"
import { Then } from "./fixtures"

/**
 * S1 — Ranks fetch table provider visibility (stubbed backend).
 *
 * Locks the FINAL REVIEW PLAN end-state: Parallel appears in the Ranks fetch
 * table via the plain `includes("fetch")` path (not just the playground
 * fetch picker), while Brave stays fetch-incapable everywhere.
 *
 * Deterministic: the stub serves 7 enabled providers; visibility is checked
 * against the rendered ranks table after the Fetch operation is selected.
 * No sleeps, no network, auto-waiting assertions only.
 */

Then(
  "the ranks fetch table should show provider {string}",
  async ({ page }, provider: string) => {
    const table = page.getByRole("table")
    await expect(table).toBeVisible()
    await expect(
      table.getByRole("row").filter({ hasText: provider })
    ).toHaveCount(1)
    await expect(
      table.getByText(provider, { exact: true })
    ).toBeVisible()
  }
)

Then(
  "the ranks fetch table should not show provider {string}",
  async ({ page }, provider: string) => {
    const table = page.getByRole("table")
    await expect(table).toBeVisible()
    await expect(
      table.getByRole("row").filter({ hasText: provider })
    ).toHaveCount(0)
  }
)
