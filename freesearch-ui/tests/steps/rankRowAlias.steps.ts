import { expect } from "@playwright/test"
import { Then } from "./fixtures"

/**
 * Singular-form alias for the authored plural rank-count step.
 *
 * The authored step in routing.steps.ts matches
 * "the ranks table should contain exactly {int} provider rows", while
 * routing.feature line 36 reads "exactly 1 provider row" (singular). The two
 * authored files disagree, so this alias registers the singular wording with
 * the exact same assertion (row count includes the header row). No authored
 * test file was modified.
 */
Then(
  "the ranks table should contain exactly {int} provider row",
  async ({ page }, count: number) => {
    const table = page.getByRole("table")
    await expect(table).toBeVisible()
    await expect(table.getByRole("row")).toHaveCount(count + 1)
  }
)
