import { expect } from "@playwright/test"
import type { Locator, Page } from "@playwright/test"
import { When, Then } from "./fixtures"

/**
 * C2 tab unification (RED): view-switching must be canonical Tabs(line)
 * (role=tab, aria-selected, line variant) and every filter must be a
 * SegmentedControl (role=group, exclusive aria-pressed).
 *
 * Churn note: the playground switcher is addressed as role=tab throughout —
 * the pre-C2 Fetch *button* query is gone on purpose, so these steps fail
 * until SearchPlayground migrates to ui/tabs.
 */

function main(page: Page): Locator {
  return page.locator("main")
}

function playgroundTab(page: Page, label: string): Locator {
  return main(page).getByRole("tab", { name: label, exact: true })
}

/** Find the one group that contains every expected option button. */
function groupWithOptions(page: Page, scope: Locator, labels: string[]): Locator {
  let group = scope.getByRole("group")
  for (const label of labels) {
    group = group.filter({
      has: page.getByRole("button", { name: new RegExp(`^${label}$`, "i") }),
    })
  }
  return group
}

async function expectExclusivePressed(
  group: Locator,
  labels: string[],
  pressed: string
): Promise<void> {
  await expect(group).toBeVisible()
  const accessibleName = await group.getAttribute("aria-label")
  expect((accessibleName ?? "").trim().length).toBeGreaterThan(0)
  for (const label of labels) {
    const button = group.getByRole("button", {
      name: new RegExp(`^${label}$`, "i"),
    })
    await expect(button).toHaveAttribute(
      "aria-pressed",
      label.toLowerCase() === pressed.toLowerCase() ? "true" : "false"
    )
  }
  // Tabs and filters never mix contracts: no option is a tab.
  await expect(group.getByRole("tab")).toHaveCount(0)
}

When("I open the playground tab {string}", async ({ page }, label: string) => {
  await playgroundTab(page, label).click()
})

When("I arrow right from the playground tab {string}", async ({ page }, label: string) => {
  await playgroundTab(page, label).focus()
  await page.keyboard.press("ArrowRight")
})

Then(
  "the playground view tabs should be canonical line tabs {string} and {string}",
  async ({ page }, first: string, second: string) => {
    const lineList = main(page).locator(
      '[data-slot="tabs-list"][data-variant="line"]'
    )
    await expect(lineList).toBeVisible()
    for (const label of [first, second]) {
      await expect(
        lineList.getByRole("tab", { name: label, exact: true })
      ).toHaveCount(1)
    }
    await expect(lineList.getByRole("tab")).toHaveCount(2)
  }
)

Then("the playground tab {string} should be selected", async ({ page }, label: string) => {
  await expect(playgroundTab(page, label)).toHaveAttribute("aria-selected", "true")
})

Then(
  "the playground tab {string} should not be selected",
  async ({ page }, label: string) => {
    await expect(playgroundTab(page, label)).toHaveAttribute(
      "aria-selected",
      "false"
    )
  }
)

Then("the playground tab {string} should have focus", async ({ page }, label: string) => {
  await expect(playgroundTab(page, label)).toBeFocused()
})

When("I activate the focused playground tab", async ({ page }) => {
  await page.keyboard.press("Enter")
})

Then("the playground tabs should be linked to their panels", async ({ page }) => {
  // Every tab names its panel and owns a stable id (Base UI wires
  // tab aria-controls <-> panel id, panel aria-labelledby <-> tab id).
  for (const label of ["Search", "Fetch"]) {
    const tab = playgroundTab(page, label)
    const controls = await tab.getAttribute("aria-controls")
    const tabId = await tab.getAttribute("id")
    expect((controls ?? "").trim().length).toBeGreaterThan(0)
    expect((tabId ?? "").trim().length).toBeGreaterThan(0)
  }
  // The selected tab's panel is the single mounted tabpanel, labelled by it.
  const selected = main(page).getByRole("tab", { selected: true })
  await expect(selected).toHaveCount(1)
  const panelId = (await selected.getAttribute("aria-controls")) ?? ""
  const tabId = (await selected.getAttribute("id")) ?? ""
  const panel = main(page).getByRole("tabpanel")
  await expect(panel).toHaveCount(1)
  await expect(panel).toHaveAttribute("id", panelId)
  await expect(panel).toHaveAttribute("aria-labelledby", tabId)
  expect(panelId.length).toBeGreaterThan(0)
  expect(tabId.length).toBeGreaterThan(0)
})

Then("the playground should show the {string} panel", async ({ page }, label: string) => {
  const tab = playgroundTab(page, label)
  const panelId = (await tab.getAttribute("aria-controls")) ?? ""
  const tabId = (await tab.getAttribute("id")) ?? ""
  expect(panelId.length).toBeGreaterThan(0)
  // Inactive panels unmount (Base UI default): exactly one tabpanel exists.
  const panels = main(page).getByRole("tabpanel")
  await expect(panels).toHaveCount(1)
  await expect(panels).toHaveAttribute("id", panelId)
  await expect(panels).toHaveAttribute("aria-labelledby", tabId)
  await expect(panels).toBeVisible()
})

Then("the fetch URL input should be visible", async ({ page }) => {
  await expect(
    main(page).getByPlaceholder(/Enter a URL to fetch/i)
  ).toBeVisible()
  await expect(
    main(page).getByRole("button", { name: "Fetch", exact: true })
  ).toBeVisible()
})

Then(
  "the depth filter should be an exclusive group of {string}, {string} and {string} with {string} pressed",
  async ({ page }, a: string, b: string, c: string, pressed: string) => {
    await expectExclusivePressed(
      groupWithOptions(page, main(page), [a, b, c]),
      [a, b, c],
      pressed
    )
  }
)

When("I choose {string} in the depth filter", async ({ page }, label: string) => {
  const group = groupWithOptions(page, main(page), ["Fast", "Balanced", "Deep"])
  await group
    .getByRole("button", { name: new RegExp(`^${label}$`, "i") })
    .click()
})

Then(
  "the providers filter should be an exclusive group of {string}, {string}, {string} and {string} with {string} pressed",
  async (
    { page },
    a: string,
    b: string,
    c: string,
    d: string,
    pressed: string
  ) => {
    await expectExclusivePressed(
      groupWithOptions(page, main(page), [a, b, c, d]),
      [a, b, c, d],
      pressed
    )
  }
)

When("I choose {string} in the providers filter", async ({ page }, label: string) => {
  const group = groupWithOptions(page, main(page), ["All", "Search", "Fetch", "Keyless"])
  await group
    .getByRole("button", { name: new RegExp(`^${label}$`, "i") })
    .click()
})

Then(
  "the providers matrix should show {int} provider rows",
  async ({ page }, count: number) => {
    const rows = main(page).getByRole("button", { name: /^(Trip|Reset)$/ })
    await expect(rows).toHaveCount(count)
  }
)

Then(
  "the providers matrix should not contain {string}",
  async ({ page }, provider: string) => {
    await expect(
      main(page).getByText(provider, { exact: true })
    ).toHaveCount(0)
  }
)

Then(
  "the activity filter should be an exclusive group of {string}, {string} and {string} with {string} pressed",
  async ({ page }, a: string, b: string, c: string, pressed: string) => {
    await expectExclusivePressed(
      groupWithOptions(page, main(page), [a, b, c]),
      [a, b, c],
      pressed
    )
  }
)

When("I choose {string} in the activity filter", async ({ page }, label: string) => {
  const group = groupWithOptions(page, main(page), ["All", "Search", "Fetch"])
  await group
    .getByRole("button", { name: new RegExp(`^${label}$`, "i") })
    .click()
})

Then(
  "the activity list should contain provider {string}",
  async ({ page }, provider: string) => {
    await expect(
      main(page).getByText(provider, { exact: true }).first()
    ).toBeVisible()
  }
)

Then(
  "the activity list should not contain provider {string}",
  async ({ page }, provider: string) => {
    await expect(
      main(page).getByText(provider, { exact: true })
    ).toHaveCount(0)
  }
)

Then(
  "the routing tabs should remain canonical line tabs {string}, {string}, {string} and {string}",
  async (
    { page },
    a: string,
    b: string,
    c: string,
    d: string
  ) => {
    const lineList = main(page).locator(
      '[data-slot="tabs-list"][data-variant="line"]'
    )
    await expect(lineList).toBeVisible()
    for (const label of [a, b, c, d]) {
      await expect(
        lineList.getByRole("tab", { name: label, exact: true })
      ).toHaveCount(1)
    }
  }
)

Then(
  "the settings tabs should remain canonical line tabs {string}, {string} and {string}",
  async ({ page }, a: string, b: string, c: string) => {
    const lineList = main(page).locator(
      '[data-slot="tabs-list"][data-variant="line"]'
    )
    await expect(lineList).toBeVisible()
    for (const label of [a, b, c]) {
      await expect(
        lineList.getByRole("tab", { name: label, exact: true })
      ).toHaveCount(1)
    }
  }
)

Then(
  "the playground should expose no button named {string} while in search mode",
  async ({ page }, label: string) => {
    await expect(playgroundTab(page, "Search")).toHaveAttribute(
      "aria-selected",
      "true"
    )
    await expect(
      main(page).getByRole("button", { name: label, exact: true })
    ).toHaveCount(0)
  }
)

Then("every playground filter toggle should live inside a group", async ({ page }) => {
  const outside = await main(page).evaluate((root) => {
    const toggles = Array.from(
      root.querySelectorAll('button[aria-pressed]')
    ) as HTMLButtonElement[]
    return toggles
      .filter((el) => el.closest('[role="group"]') === null)
      .map((el) => el.textContent?.trim() ?? "")
  })
  expect(outside).toEqual([])
})

Then("the header navigation should expose zero tab roles", async ({ page }) => {
  const header = page.locator("header")
  await expect(header.getByRole("tab")).toHaveCount(0)
  await expect(header.getByRole("tablist")).toHaveCount(0)
  await expect(header.getByRole("button")).toHaveCount(6)
})

Then("the page URL should be unchanged", async ({ page }) => {
  // No router is introduced by C2: view tab switches keep path + query stable.
  expect(page.url()).not.toMatch(/[?#]/)
  expect(new URL(page.url()).pathname).toBe("/")
})
