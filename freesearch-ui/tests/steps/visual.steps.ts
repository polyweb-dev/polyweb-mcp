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
  await expect(page).toHaveScreenshot(snapshotName, {
    animations: "disabled",
    maxDiffPixelRatio: 0.01,
    mask: dynamicRegions(page),
  })
})

Then(
  "the focused-control screenshot {string} should match",
  async ({ page }, snapshotName: string) => {
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

Then("reduced-motion transitions should be disabled", async ({ page }) => {
  const strategyCard = page.getByRole("button", { name: /^Strict priority/ })
  await expect(strategyCard).toBeVisible()
  expect(await transitionDuration(strategyCard)).toBe("0s")

  await page.getByRole("tab", { name: "Simulator", exact: true }).click()
  const simulatorGroup = page.getByRole("group", {
    name: "Simulator operation",
    exact: true,
  })
  const segmentedButton = simulatorGroup.getByRole("button", {
    name: "Search",
    exact: true,
  })
  await expect(segmentedButton).toBeVisible()
  expect(await transitionDuration(segmentedButton)).toBe("0s")

  await page.getByRole("tab", { name: "Strategy", exact: true }).click()
  await expect(strategyCard).toBeVisible()
})

When("I walk from the header through Routing with keyboard only", async ({ page }) => {
  const headerLabels = ["Playground", "Providers", "Routing"]
  for (const label of headerLabels) {
    await page.keyboard.press("Tab")
    await expectFocusVisible(page.getByRole("button", { name: label, exact: true }))
  }

  const routingButton = page.getByRole("button", { name: "Routing", exact: true })
  await page.keyboard.press("Enter")
  await expect(page.getByRole("heading", { name: "Routing", exact: true })).toBeVisible()
  await expectFocusVisible(routingButton)

  for (const label of ["Usage", "Activity", "Settings"]) {
    await page.keyboard.press("Tab")
    await expectFocusVisible(page.getByRole("button", { name: label, exact: true }))
  }

  const strategyTab = page.getByRole("tab", { name: "Strategy", exact: true })
  await page.keyboard.press("Tab")
  await expectFocusVisible(strategyTab)

  const strategyPanel = page.getByRole("tabpanel", { name: "Strategy", exact: true })
  await page.keyboard.press("Tab")
  await expectFocusVisible(strategyPanel)

  const firstStrategyCard = page.getByRole("button", { name: /^Strict priority/ })
  await page.keyboard.press("Tab")
  await expectFocusVisible(firstStrategyCard)
})

When("I move to the {string} view using keyboard only", async ({ page }, view: string) => {
  const navigationButton = page.getByRole("button", { name: view, exact: true })
  await navigationButton.focus()
  await expectFocusVisible(navigationButton)
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

When("I press Space on the focused failover switch", async ({ page }) => {
  const switchControl = switchByLabel(page, "Fallback chaining")
  await expect(switchControl).toBeFocused()
  const before = await switchControl.getAttribute("aria-checked")
  expect(before).toMatch(/^(true|false)$/)

  await page.keyboard.press("Space")
  await expect(switchControl).toHaveAttribute(
    "aria-checked",
    before === "true" ? "false" : "true"
  )
})

Then("the failover sub-switches should remain reachable by Tab", async ({ page }) => {
  for (const label of [
    "Failover on rate limit (429)",
    "Failover on timeout",
    "Failover on server error (5xx)",
  ]) {
    await page.keyboard.press("Tab")
    await expectFocusVisible(switchByLabel(page, label))
  }
})

When(
  "I open the {string} routing tab using keyboard only",
  async ({ page }, tabLabel: string) => {
    const tab = page.getByRole("tab", { name: tabLabel, exact: true })
    await tab.focus()
    await expectFocusVisible(tab)
    await page.keyboard.press("Enter")
    await expect(tab).toHaveAttribute("aria-selected", "true")
  }
)

When(
  "I choose {string} in the simulator operation using keyboard only",
  async ({ page }, operation: string) => {
    const simulatorGroup = page.getByRole("group", {
      name: "Simulator operation",
      exact: true,
    })
    const current = simulatorGroup.getByRole("button", { name: "Search", exact: true })
    const requested = simulatorGroup.getByRole("button", { name: operation, exact: true })

    await current.focus()
    await expectFocusVisible(current)
    await page.keyboard.press("Tab")
    await expectFocusVisible(requested)
    await page.keyboard.press("Space")
    await expect(requested).toHaveAttribute("aria-pressed", "true")
  }
)

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
  await expect(page.getByText("FreeSearch", { exact: true })).toBeVisible()
}

function dynamicRegions(page: Page): Locator[] {
  return [
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

async function transitionDuration(locator: Locator): Promise<string> {
  return locator.evaluate((element) => getComputedStyle(element).transitionDuration)
}

async function expectFocusVisible(locator: Locator): Promise<void> {
  await expect(locator).toBeFocused()
  const isFocusVisible = await locator.evaluate(
    (element) => document.activeElement === element && element.matches(":focus-visible")
  )
  expect(isFocusVisible).toBe(true)
}
