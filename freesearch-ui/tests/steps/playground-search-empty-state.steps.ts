import { expect } from "@playwright/test"
import { When, Then } from "./fixtures"

/**
 * PG-S1 Search empty state (Red).
 *
 * Wrapper contract (Developer implements exactly this in PlaygroundPage):
 *   <div data-testid="search-layout" data-state="hero|docked" ...>
 * Idle -> hero (centered, min-h ~55-60vh, max-w-3xl); any search content
 * (activeSearch / isSearching / searchError) -> docked (top, results below).
 * Animation: transition-all duration-300 ease-out motion-reduce:transition-none.
 */

Then("the search request zone should be in hero state", async ({ page }) => {
  const zone = page.getByTestId("search-layout")
  await expect(zone).toHaveAttribute("data-state", "hero")
  const cls = (await zone.getAttribute("class")) ?? ""
  expect(cls).toContain("transition-all")
  expect(cls).toContain("duration-300")
  expect(cls).toContain("ease-out")
  expect(cls).toContain("motion-reduce:transition-none")
  expect(cls).toMatch(/min-h-\[(55|60)vh\]/)
  expect(cls).toContain("max-w-3xl")
  expect(cls).not.toContain("top-docked")
})

Then("the search request zone should be in docked state", async ({ page }) => {
  const zone = page.getByTestId("search-layout")
  await expect(zone).toHaveAttribute("data-state", "docked")
  const cls = (await zone.getAttribute("class")) ?? ""
  expect(cls).toContain("top-docked")
  expect(cls).toContain("transition-all")
  expect(cls).toContain("duration-300")
  expect(cls).toContain("ease-out")
  expect(cls).toContain("motion-reduce:transition-none")
})

Then(
  "the search form should be present with no search results",
  async ({ page }) => {
    await expect(
      page.getByPlaceholder(/Search across all providers/i)
    ).toBeVisible()
    await expect(page.getByTestId("search-layout")).toBeVisible()
    // No result cards and no telemetry bar on the empty/error-first surface.
    await expect(page.getByText(/% match/i)).toHaveCount(0)
    await expect(page.getByText(/Returned results/i)).toHaveCount(0)
  }
)

Then(
  "the search results should render below the search form",
  async ({ page }) => {
    const form = page.getByPlaceholder(/Search across all providers/i)
    const resultsHeading = page.getByText(/Returned results|% match/i).first()
    await expect(resultsHeading).toBeVisible()
    const formBox = await form.boundingBox()
    const resultsBox = await resultsHeading.boundingBox()
    expect(formBox).not.toBeNull()
    expect(resultsBox).not.toBeNull()
    expect(resultsBox!.y).toBeGreaterThan(formBox!.y)
  }
)

Then("the search request zone should animate smoothly", async ({ page }) => {
  const zone = page.getByTestId("search-layout")
  await expect(zone).toBeVisible()
  const cls = (await zone.getAttribute("class")) ?? ""
  expect(cls).toContain("transition-all")
  expect(cls).toContain("duration-300")
  expect(cls).toContain("ease-out")
  expect(cls).toContain("motion-reduce:transition-none")
})

Then(
  "the search form should keep its value {string}",
  async ({ page }, value: string) => {
    await expect(
      page.getByPlaceholder(/Search across all providers/i)
    ).toHaveValue(value)
  }
)

// Re-export guard: keep this module's When import referenced so lint does not
// flag the shared fixture import as unused.
void When
