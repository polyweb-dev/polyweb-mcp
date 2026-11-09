import { expect } from "@playwright/test"
import { Then } from "./fixtures"

/** The search composer stays docked at full width in every request state. */

Then("the search request zone should be in docked state", async ({ page }) => {
  const zone = page.getByTestId("search-layout")
  await expect(zone).toHaveAttribute("data-state", "docked")
  const cls = (await zone.getAttribute("class")) ?? ""
  expect(cls).toContain("top-docked")
  expect(cls).toContain("w-full")
})

Then(
  "the search form should be present with no search results",
  async ({ page }) => {
    await expect(
      page.getByPlaceholder(/Search the web/i)
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
    const form = page.getByPlaceholder(/Search the web/i)
    const resultsHeading = page.getByText(/Returned results|% match/i).first()
    await expect(resultsHeading).toBeVisible()
    const formBox = await form.boundingBox()
    const resultsBox = await resultsHeading.boundingBox()
    expect(formBox).not.toBeNull()
    expect(resultsBox).not.toBeNull()
    expect(resultsBox!.y).toBeGreaterThan(formBox!.y)
  }
)

Then("the search request zone should stay full width without a layout transition", async ({ page }) => {
  const zone = page.getByTestId("search-layout")
  await expect(zone).toHaveAttribute("data-state", "docked")
  const cls = (await zone.getAttribute("class")) ?? ""
  expect(cls.split(/\s+/)).toEqual(expect.arrayContaining(["top-docked", "w-full"]))
  expect(cls).not.toContain("transition-all")
  expect(cls).not.toMatch(/min-h-|max-w-3xl/)
})

Then(
  "the search form should keep its value {string}",
  async ({ page }, value: string) => {
    await expect(
      page.getByPlaceholder(/Search the web/i)
    ).toHaveValue(value)
  }
)

