import { expect, type Locator, type Page } from "@playwright/test"
import { Given, When, Then } from "./fixtures"

const DETERMINISTIC_VISUAL_CSS = `
  *, *::before, *::after {
    animation-duration: 0s !important;
    animation-delay: 0s !important;
    transition-duration: 0s !important;
    transition-delay: 0s !important;
    scroll-behavior: auto !important;
  }
`

Given("I open the visual app at {int} by {int}", async ({ page }, width: number, height: number) => {
  await openVisualApp(page, width, height, false)
})

Given(
  "I open the visual app at {int} by {int} with reduced motion",
  async ({ page }, width: number, height: number) => {
    await openVisualApp(page, width, height, true)
  }
)

Then("the visual page screenshot {string} should match", async ({ page }, snapshotName: string) => {
  await waitForDeterministicData(page)
  await expect(page).toHaveScreenshot(snapshotName, {
    animations: "disabled",
    maxDiffPixelRatio: 0.01,
    mask: dynamicRegions(page),
  })
})

Then(
  "the focused-control screenshot {string} should match",
  async ({ page }, snapshotName: string) => {
    await waitForDeterministicData(page)
    const focusedControl = page.locator(":focus")
    await expect(focusedControl).toHaveCount(1)
    await expect(focusedControl).toBeFocused()
    await expect(focusedControl).toHaveScreenshot(snapshotName, {
      animations: "disabled",
      maxDiffPixelRatio: 0.01,
      mask: dynamicRegions(page),
    })
  }
)

When("I move to the {string} view using keyboard only", async ({ page }, view: string) => {
  let navigationLink = page.getByRole("link", { name: view, exact: true })
  const openNavigation = page.getByRole("button", { name: "Open navigation", exact: true })
  // Permission-gated links appear once system access has loaded (U1).
  await expect(navigationLink.or(openNavigation).first()).toBeVisible()
  if (!(await navigationLink.isVisible())) {
    await openNavigation.click()
    navigationLink = page
      .getByRole("dialog", { name: "Navigation" })
      .getByRole("link", { name: view, exact: true })
  }
  await navigationLink.focus()
  await page.keyboard.press("Tab")
  await page.keyboard.press("Shift+Tab")
  await expectFocusVisible(navigationLink)
  await page.keyboard.press("Enter")
  await expect(page.getByRole("heading", { name: view, exact: true })).toBeVisible()
})

When(
  "I open the {string} settings tab using keyboard only",
  async ({ page }, tabLabel: string) => {
    const tab = page.getByRole("tab", { name: tabLabel, exact: true })
    await tab.focus()
    await expectFocusVisible(tab)
    await page.keyboard.press("Enter")
    await expect(tab).toHaveAttribute("aria-selected", "true")
  }
)

When(
  "I focus the {string} switch using keyboard only",
  async ({ page }, switchLabel: string) => {
    const switchControl = switchByLabel(page, switchLabel)
    await switchControl.focus()
    await expectFocusVisible(switchControl)
  }
)

When("I press Space on the focused fallback switch", async ({ page }) => {
  const switchControl = switchByLabel(page, "Fallback")
  await expect(switchControl).toBeFocused()
  const before = await switchControl.getAttribute("aria-checked")
  expect(before).toMatch(/^(true|false)$/)

  await page.keyboard.press("Space")
  await expect(switchControl).toHaveAttribute(
    "aria-checked",
    before === "true" ? "false" : "true"
  )
})

Then("the max attempts controls should remain reachable by Tab", async ({ page }) => {
  // Turning fallback off hides the stepper. Turn it back on with the
  // keyboard, then continue through the controls in document order.
  const fallback = switchByLabel(page, "Fallback")
  await expect(fallback).toBeFocused()
  if ((await fallback.getAttribute("aria-checked")) === "false") {
    await page.keyboard.press("Space")
    await expect(fallback).toBeChecked()
  }
  for (const label of ["Decrease max attempts", "Increase max attempts"]) {
    await page.keyboard.press("Tab")
    await expectFocusVisible(page.getByRole("button", { name: label, exact: true }))
  }
})

async function openVisualApp(
  page: Page,
  width: number,
  height: number,
  reducedMotion: boolean
): Promise<void> {
  await page.setViewportSize({ width, height })
  await page.emulateMedia({ reducedMotion: reducedMotion ? "reduce" : "no-preference" })
  await page.goto("/")
  await page.addStyleTag({ content: DETERMINISTIC_VISUAL_CSS })
  await page.evaluate(() => document.fonts.ready)
  const shellMarker =
    width < 768
      ? page.getByRole("button", { name: "Open navigation", exact: true })
      : page.getByText("FreeSearch", { exact: true })
  await expect(shellMarker).toBeVisible()
}

/**
 * Settle gate for screenshots: the shell logo (awaited in openVisualApp)
 * paints before backend data resolves, so screenshots must additionally await
 * a data-loaded signal. The Settings Providers/Keys tabs render the stub
 * catalog names and the Providers tab renders its Fallback switch.
 */
async function waitForDeterministicData(page: Page): Promise<void> {
  const dataSignal = page
    .getByText("Brave Search", { exact: true })
    .or(page.getByRole("switch", { name: "Fallback", exact: true }))
  await expect(dataSignal.first()).toBeVisible({ timeout: 15_000 })
}

function dynamicRegions(page: Page): Locator[] {  return [
    page.locator("time"),
    page.locator(".tnum"),
    page.locator("div.fixed.bottom-4.right-4.z-50"),
    page.locator('[role="status"], [data-sonner-toaster], [data-testid*="toast"]'),
    page.locator(
      '[data-testid*="timestamp"], [data-testid*="latency"], [data-testid*="quota"], [data-testid*="cost"]'
    ),
  ]
}

function switchByLabel(page: Page, label: string): Locator {
  return page.getByRole("switch", { name: new RegExp(`^${escapeRegExp(label)}`) })
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

async function expectFocusVisible(locator: Locator): Promise<void> {
  await expect(locator).toBeFocused()
  const isFocusVisible = await locator.evaluate(
    (element) => document.activeElement === element && element.matches(":focus-visible")
  )
  expect(isFocusVisible).toBe(true)
}
