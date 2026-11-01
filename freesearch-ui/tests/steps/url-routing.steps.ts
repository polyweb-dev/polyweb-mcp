import { expect } from "@playwright/test"
import { When, Then } from "./fixtures"

/**
 * C4 URL routing — history-aware step definitions (NEW, Red phase).
 *
 * Real BrowserRouter history: direct navigation (page.goto), link hrefs,
 * aria-current markers, back/forward, and reload. Pill-tab steps are reused
 * from routing.steps.ts / settings.steps.ts — this file only adds the
 * URL-path assertions around them.
 *
 * Step-text uniqueness: none of these patterns exist in workspace.steps.ts,
 * routing.steps.ts, tab-unification.steps.ts, settings.steps.ts,
 * activity.steps.ts, playground.steps.ts, theme.steps.ts, or visual.steps.ts.
 */

When("I navigate directly to {string}", async ({ page }, path: string) => {
  await page.goto(path)
})

Then("the page URL path should be {string}", async ({ page }, expected: string) => {
  await expect(async () => {
    expect(new URL(page.url()).pathname).toBe(expected)
  }).toPass({ timeout: 10_000 })
})

Then("the page URL path should still be {string}", async ({ page }, expected: string) => {
  // Pill-tab switches must not push history entries.
  await expect(page.getByRole("tab").first()).toBeVisible().catch(() => {})
  expect(new URL(page.url()).pathname).toBe(expected)
})

When("I go back in history", async ({ page }) => {
  await page.goBack()
})

When("I go forward in history", async ({ page }) => {
  await page.goForward()
})

When("I reload the page", async ({ page }) => {
  await page.reload()
})

Then(
  "the {string} sidebar link should be marked current",
  async ({ page }, label: string) => {
    const link = page.getByRole("link", { name: label, exact: true })
    await expect(link).toBeVisible()
    await expect(link).toHaveAttribute("aria-current", "page")
    const nav = page.getByRole("navigation", { name: "Primary" })
    await expect(nav.locator('[aria-current="page"]')).toHaveCount(1)
  }
)

Then(
  "the {string} sidebar link should point to {string}",
  async ({ page }, label: string, href: string) => {
    await expect(page.getByRole("link", { name: label, exact: true })).toHaveAttribute(
      "href",
      href
    )
  }
)

Then("the shell should expose no header element", async ({ page }) => {
  await expect(page.locator("header")).toHaveCount(0)
})

/**
 * Primary links of the default stubbed session, a system administrator (every
 * system permission), in the U2 contract order: Playground and Activity moved
 * to the Project navigation and the installation usage link is "Provider
 * usage".
 */
const SYSTEM_ADMINISTRATOR_LINKS = [
  "Routing",
  "Provider usage",
  "Settings",
  "Projects",
  "Account",
  "Admin",
]

Then(
  "the sidebar navigation should expose the system administrator links",
  async ({ page }) => {
    const nav = page.getByRole("navigation", { name: "Primary" })
    await expect(nav).toBeVisible()
    const links = nav.getByRole("link")
    await expect(links).toHaveCount(SYSTEM_ADMINISTRATOR_LINKS.length)
    // P1-FINAL: standalone Providers page retired into Settings — no link.
    await expect(nav.getByRole("link", { name: "Providers", exact: true })).toHaveCount(0)
    for (const [index, label] of SYSTEM_ADMINISTRATOR_LINKS.entries()) {
      await expect(links.nth(index)).toHaveAccessibleName(label)
    }
  }
)
