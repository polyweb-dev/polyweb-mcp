import { expect, type Locator, type Page } from "@playwright/test"
import { Given, Then, When } from "./fixtures"
import { apiKeyTraffic, seedProjectStubApiKey } from "./projectStub"
import { secondTab } from "./tabs"

/**
 * Project API key acceptance (TASK-000046 U1, AC #3 and #4).
 *
 * Accessible names follow the U1 UI contract verbatim. The raw key is read
 * from the stub's own record (apiKeyTraffic.rawKeys) rather than from the page,
 * so each check proves where that exact value is and is not. Assertions match
 * the secret part of the key too, so a stored fragment would also fail. Stub
 * keys are plainly fake (`fs_live_stubprefixNN_FAKE...`).
 */

function issueSection(page: Page): Locator {
  return page.getByRole("region", { name: "New API key" })
}

function revealDialog(page: Page): Locator {
  return page.getByRole("dialog", { name: "Copy your new API key" })
}

function keysTable(page: Page): Locator {
  return page.getByRole("table", { name: "API keys" })
}

function keyRows(page: Page, label: string): Locator {
  return keysTable(page)
    .getByRole("row")
    .filter({ has: page.getByRole("cell", { name: label, exact: true }) })
}

function latestRawKey(): string {
  const raw = apiKeyTraffic.rawKeys.at(-1)
  if (raw === undefined) throw new Error("the stub revealed no API key")
  return raw
}

/** The secret part after the last separator: never shown after the reveal. */
function secretOf(raw: string): string {
  return raw.slice(raw.lastIndexOf("_") + 1)
}

async function issueKey(page: Page, label: string | null, expiration: string): Promise<void> {
  const section = issueSection(page)
  await expect(section).toBeVisible({ timeout: 15_000 })
  if (label !== null) await section.getByLabel("Label", { exact: true }).fill(label)
  const choice = section
    .getByRole("group", { name: "Expiration", exact: true })
    .getByRole("button", { name: expiration, exact: true })
  await choice.click()
  await expect(choice).toHaveAttribute("aria-pressed", "true")
  await section.getByRole("button", { name: "Issue key", exact: true }).click()
}

async function closeReveal(page: Page): Promise<void> {
  const dialog = revealDialog(page)
  await dialog.getByRole("button", { name: "Done", exact: true }).click()
  await expect(dialog).toHaveCount(0)
}

Given(
  "project {word} has an API key labelled {string}",
  async ({ page: _page }, projectName: string, label: string) => {
    seedProjectStubApiKey(projectName, label, { expiresInDays: 30, lastUsedMinutesAgo: 5 })
  }
)

When(
  "I issue an API key labelled {string} with {string}",
  async ({ page }, label: string, expiration: string) => {
    await issueKey(page, label, expiration)
  }
)

Then("the issue request asked for no expiration", async () => {
  await expect.poll(() => apiKeyTraffic.issueBodies.length).toBe(1)
  const body = apiKeyTraffic.issueBodies[0]
  // "No expiration" sends an explicit null; an omitted field would mean 90 days.
  expect(Object.prototype.hasOwnProperty.call(body, "expires_at")).toBe(true)
  expect(body.expires_at).toBeNull()
})

Then("the new API key is revealed once with the shown-only-once warning", async ({ page }) => {
  const dialog = revealDialog(page)
  await expect(dialog).toBeVisible({ timeout: 15_000 })
  const raw = latestRawKey()
  await expect(dialog.getByText("This key is shown only once.")).toBeVisible()
  await expect(dialog.getByLabel("API key", { exact: true })).toHaveValue(raw)
  await expect(dialog.getByRole("button", { name: "Copy key", exact: true })).toBeVisible()
  // Exactly one place on the page holds the raw key: the dialog's read-only field.
  const holders = await page.evaluate((secret) => {
    let count = 0
    for (const field of Array.from(document.querySelectorAll("input, textarea"))) {
      if ((field as HTMLInputElement).value.includes(secret)) count += 1
    }
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
    for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
      if ((node.textContent ?? "").includes(secret)) count += 1
    }
    return count
  }, secretOf(raw))
  expect(holders).toBe(1)
})

Then("the revealed API key is in neither browser storage nor the URL", async ({ page }) => {
  const leaks = await page.evaluate((secret) => {
    const hits: string[] = []
    for (const [name, store] of [
      ["localStorage", window.localStorage],
      ["sessionStorage", window.sessionStorage],
    ] as const) {
      for (let index = 0; index < store.length; index += 1) {
        const key = store.key(index) ?? ""
        if (key.includes(secret) || (store.getItem(key) ?? "").includes(secret)) {
          hits.push(`${name}:${key}`)
        }
      }
    }
    if (window.location.href.includes(secret)) hits.push("url")
    if (JSON.stringify(window.history.state ?? null).includes(secret)) hits.push("history")
    return hits
  }, secretOf(latestRawKey()))
  expect(leaks).toEqual([])
})

When("I close the API key reveal dialog", async ({ page }) => {
  await closeReveal(page)
})

Then("the revealed API key is gone from the page", async ({ page }) => {
  await expect(revealDialog(page)).toHaveCount(0)
  const leaks = await page.evaluate((secret) => {
    const hits: string[] = []
    for (const field of Array.from(document.querySelectorAll("input, textarea"))) {
      if ((field as HTMLInputElement).value.includes(secret)) hits.push("field")
    }
    if (document.documentElement.outerHTML.includes(secret)) hits.push("markup")
    if (document.body.innerText.includes(secret)) hits.push("text")
    return hits
  }, secretOf(latestRawKey()))
  expect(leaks).toEqual([])
})

Then(
  "the API key row {string} shows {string}",
  async ({ page }, label: string, text: string) => {
    const row = keyRows(page, label)
    await expect(row).toHaveCount(1, { timeout: 15_000 })
    await expect(row).toContainText(text)
  }
)

When("I rotate the API key {string} with the default options", async ({ page }, label: string) => {
  await page.getByRole("button", { name: `Actions for ${label}`, exact: true }).click()
  await page.getByRole("button", { name: "Rotate", exact: true }).click()
  const dialog = page.getByRole("dialog", { name: `Rotate ${label}` })
  await expect(dialog).toBeVisible()
  const overlap = dialog.getByLabel("Old key stays valid for", { exact: true })
  const tag = await overlap.evaluate((element) => element.tagName)
  if (tag === "SELECT") await expect(overlap).toHaveValue("86400")
  else await expect(overlap).toContainText("24 hours")
  await expect(
    dialog
      .getByRole("group", { name: "Expiration", exact: true })
      .getByRole("button", { name: "Keep current", exact: true })
  ).toHaveAttribute("aria-pressed", "true")
  await dialog.getByRole("button", { name: "Rotate key", exact: true }).click()
})

Then("the rotate request kept the 24 hour overlap and the current lifetime", async () => {
  await expect.poll(() => apiKeyTraffic.rotateBodies.length).toBe(1)
  const body = apiKeyTraffic.rotateBodies[0]
  // 86400 seconds; the backend applies the same default when the field is omitted.
  expect(body.overlap_seconds ?? 86_400).toBe(86_400)
  // "Keep current" omits expires_at (null would mean no expiration).
  expect(Object.prototype.hasOwnProperty.call(body, "expires_at")).toBe(false)
})

Then(
  "the API keys table lists {int} rows labelled {string}",
  async ({ page }, count: number, label: string) => {
    await expect(keyRows(page, label)).toHaveCount(count, { timeout: 15_000 })
  }
)

When("I revoke the API key {string} and confirm", async ({ page }, label: string) => {
  await page.getByRole("button", { name: `Actions for ${label}`, exact: true }).click()
  await page.getByRole("button", { name: "Revoke", exact: true }).click()
  await page
    .getByRole("dialog", { name: `Revoke ${label}` })
    .getByRole("button", { name: "Revoke key", exact: true })
    .click()
  await expect.poll(() => apiKeyTraffic.revokedIds.length).toBe(1)
})

Then(
  "the API key row {string} offers no Rotate or Revoke action",
  async ({ page }, label: string) => {
    await expect(keyRows(page, label)).toHaveCount(1)
    await expect(page.getByRole("button", { name: `Actions for ${label}`, exact: true })).toHaveCount(0)
  }
)

Then("the Project navigation lists exactly {string}", async ({ page }, list: string) => {
  const labels = list.split(",").map((label) => label.trim())
  const links = page.getByRole("navigation", { name: "Project" }).getByRole("link")
  await expect(links).toHaveCount(labels.length, { timeout: 15_000 })
  for (const [index, label] of labels.entries()) {
    await expect(links.nth(index)).toHaveAccessibleName(label)
  }
})

Then("the API key issue form is absent", async ({ page }) => {
  await expect(issueSection(page)).toHaveCount(0)
  await expect(page.getByRole("button", { name: "Issue key", exact: true })).toHaveCount(0)
})

When(
  "I type {string} into the API key label of the second tab",
  async ({ page: _page }, value: string) => {
    const section = issueSection(secondTab())
    await expect(section).toBeVisible({ timeout: 15_000 })
    await section.getByLabel("Label", { exact: true }).fill(value)
  }
)

Then("the first tab's API key label is empty", async ({ page }) => {
  const section = issueSection(page)
  await expect(section).toBeVisible({ timeout: 15_000 })
  await expect(section.getByLabel("Label", { exact: true })).toHaveValue("")
})

When(
  "I issue the drafted API key with {string} in the second tab",
  async ({ page: _page }, expiration: string) => {
    const tab = secondTab()
    await issueKey(tab, null, expiration)
    await expect(revealDialog(tab)).toBeVisible({ timeout: 15_000 })
    await closeReveal(tab)
  }
)

Then("the first tab lists the API key {string}", async ({ page }, label: string) => {
  await expect(keyRows(page, label)).toHaveCount(1, { timeout: 15_000 })
})

Then("the first tab does not list the API key {string}", async ({ page }, label: string) => {
  await expect(page.getByRole("cell", { name: label, exact: true })).toHaveCount(0)
})

Then("the second tab lists the API key {string}", async ({ page: _page }, label: string) => {
  const tab = secondTab()
  await expect(keyRows(tab, label)).toHaveCount(1, { timeout: 15_000 })
})

Then(
  "the second tab does not list the API key {string}",
  async ({ page: _page }, label: string) => {
    await expect(secondTab().getByRole("cell", { name: label, exact: true })).toHaveCount(0)
  }
)

Then("the first tab has no API keys screen", async ({ page }) => {
  await expect(issueSection(page)).toHaveCount(0, { timeout: 15_000 })
  await expect(
    page.getByRole("navigation", { name: "Project" }).getByRole("link", { name: "API keys", exact: true })
  ).toHaveCount(0)
})

Then("the second tab still offers the API key issue form", async ({ page: _page }) => {
  await expect(issueSection(secondTab())).toBeVisible({ timeout: 15_000 })
})

/** Assert one element lies fully inside the viewport with the page unscrolled. */
async function expectWithinViewport(page: Page, locator: Locator): Promise<void> {
  await expect(locator).toBeVisible({ timeout: 15_000 })
  const scroll = await page.evaluate(() => ({ x: window.scrollX, y: window.scrollY }))
  expect(scroll).toEqual({ x: 0, y: 0 })
  const box = await locator.boundingBox()
  const viewport = page.viewportSize()
  expect(box).not.toBeNull()
  expect(viewport).not.toBeNull()
  if (box === null || viewport === null) return
  expect(box.width).toBeGreaterThan(0)
  expect(box.height).toBeGreaterThan(0)
  expect(box.x).toBeGreaterThanOrEqual(0)
  expect(box.y).toBeGreaterThanOrEqual(0)
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width)
  expect(box.y + box.height).toBeLessThanOrEqual(viewport.height)
}

When(
  "I open the workspace page {string} at {int} by {int}",
  async ({ page }, path: string, width: number, height: number) => {
    await page.setViewportSize({ width, height })
    await page.goto(path)
  }
)

Then(
  "the project selector names {string} within the viewport",
  async ({ page }, name: string) => {
    await expectWithinViewport(
      page,
      page.getByRole("button", { name: `Select project (current: ${name})`, exact: true })
    )
  }
)

Then(
  "the project selector shows {string} without clipping",
  async ({ page }, name: string) => {
    const trigger = page.getByRole("button", {
      name: `Select project (current: ${name})`,
      exact: true,
    })
    await expect(trigger).toBeVisible({ timeout: 15_000 })
    await expect(trigger).toContainText(name)
    const label = trigger.locator("span").first()
    const fits = await label.evaluate(
      (element) => element.scrollWidth <= element.clientWidth
    )
    expect(fits).toBe(true)
  }
)

Then("the Back link {string} is absent", async ({ page }, name: string) => {
  await expect(
    page.getByRole("navigation", { name: "Project" }).getByRole("link", {
      name: `Back to ${name}`,
      exact: true,
    })
  ).toHaveCount(0)
})

Then(
  "the active Project link {string} is current within the viewport",
  async ({ page }, label: string) => {
    const link = page
      .getByRole("navigation", { name: "Project" })
      .getByRole("link", { name: label, exact: true })
    await expectWithinViewport(page, link)
    await expect(link).toHaveAttribute("aria-current", "page")
  }
)

Then("the heading {string} is within the viewport", async ({ page }, name: string) => {
  await expectWithinViewport(page, page.getByRole("heading", { name, exact: true }).first())
})
