import type { Locator, Page } from "@playwright/test"

/** The provider's measurable card or its compact balance/unreported-usage row. */
export function providerQuotaSurface(page: Page, provider: string): Locator {
  const name = provider === "Brave" ? "Brave Search" : provider
  const quiet = page.getByRole("list", { name: "Provider balances and unreported usage", exact: true })
    .getByRole("listitem")
  return page.locator("article").or(quiet).filter({
    has: page.getByRole("heading", { name, exact: true }),
  })
}
