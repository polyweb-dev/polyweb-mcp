import type { Page } from "@playwright/test"

/**
 * The second tab of a two-tab scenario, shared by the project step files.
 * One browser context holds both tabs, so they share cookies and the
 * module-level project stub state, exactly like two real tabs.
 */
let secondPage: Page | null = null

export function setSecondTab(page: Page | null): void {
  secondPage = page
}

export function secondTab(): Page {
  if (secondPage === null) throw new Error("second tab not open")
  return secondPage
}
