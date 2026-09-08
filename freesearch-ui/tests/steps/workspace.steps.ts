import { expect } from "@playwright/test"
import { Given, When, Then } from "./fixtures"

/**
 * C4 URL routing — sidebar workspace navigation (REWRITTEN, Red phase).
 *
 * Blessed churn (NOT weakening): the pre-C4 no-router/button-only pins are
 * VOID. Sidebar nav is router links (NavLink), not buttons:
 *   - `getByRole("button")` -> `getByRole("link")` for sidebar nav;
 *   - navigation changes the URL (route table in App.tsx).
 *
 * The legacy "header tab" phrasing is kept as an alias so pre-C4 features
 * (routing, tab-unification, settings, activity, visual) still resolve —
 * they now assert the link contract and go Red until the router lands.
 * New C4 scenarios should prefer the explicit "sidebar link" phrasing.
 * URL-path assertions live in url-routing.steps.ts.
 */

Given("I navigate to the web application", async ({ page }) => {
  await page.goto("/")
  await expect(page.getByText("FreeSearch", { exact: true })).toBeVisible()
})

When("I select the {string} header tab", async ({ page }, tabLabel: string) => {
  await followSidebarLink(page, tabLabel)
})

When("I follow the {string} sidebar link", async ({ page }, label: string) => {
  await followSidebarLink(page, label)
})

async function followSidebarLink(page: import("@playwright/test").Page, label: string) {
  let link = page.getByRole("link", { name: label, exact: true })
  if (!(await link.isVisible())) {
    await page.getByRole("button", { name: "Open navigation", exact: true }).click()
    link = page
      .getByRole("dialog", { name: "Navigation" })
      .getByRole("link", { name: label, exact: true })
  }
  await link.click()
}

Then("I should see the {string} heading", async ({ page }, heading: string) => {
  await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible()
})
