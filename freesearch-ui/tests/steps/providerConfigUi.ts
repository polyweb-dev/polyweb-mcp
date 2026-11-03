import { expect } from "@playwright/test"
import type { Locator, Page } from "@playwright/test"

/**
 * Shared UI helpers of the U3 provider configuration scenarios: browser-side
 * evidence (every request and console line, for secret-leak checks) and
 * tolerant form controls (a native select or a listbox combobox).
 */

interface SeenRequest {
  method: string
  url: string
  body: string
}

const seenRequests: SeenRequest[] = []
const seenConsole: string[] = []
const watchedPages = new WeakSet<Page>()

/** Start recording every request and console message of this tab. */
export function watchBrowserTraffic(page: Page): void {
  seenRequests.length = 0
  seenConsole.length = 0
  if (watchedPages.has(page)) return
  watchedPages.add(page)
  page.on("request", (request) => {
    seenRequests.push({ method: request.method(), url: request.url(), body: request.postData() ?? "" })
  })
  page.on("console", (message) => {
    seenConsole.push(message.text())
  })
}

/** Requests whose URL or body contains this text. */
export function requestsCarrying(text: string): SeenRequest[] {
  return seenRequests.filter((r) => r.url.includes(text) || r.body.includes(text))
}

/** Console lines containing this text. */
export function consoleCarrying(text: string): string[] {
  return seenConsole.filter((line) => line.includes(text))
}

/** Places in the page, browser storage, URL and history state that hold this text. */
export async function secretLeaks(page: Page, secret: string): Promise<string[]> {
  return page.evaluate((needle) => {
    const hits: string[] = []
    if (document.documentElement.outerHTML.includes(needle)) hits.push("dom")
    for (const input of Array.from(document.querySelectorAll("input, textarea"))) {
      if ((input as HTMLInputElement).value.includes(needle)) hits.push("input-value")
    }
    for (const [name, store] of [
      ["localStorage", window.localStorage],
      ["sessionStorage", window.sessionStorage],
    ] as const) {
      for (let index = 0; index < store.length; index += 1) {
        const key = store.key(index) ?? ""
        if (key.includes(needle) || (store.getItem(key) ?? "").includes(needle)) hits.push(`${name}:${key}`)
      }
    }
    if (window.location.href.includes(needle)) hits.push("url")
    if (JSON.stringify(window.history.state ?? null).includes(needle)) hits.push("history")
    return hits
  }, secret)
}

/**
 * One labelled form control by its accessible name. A label that wraps a
 * select also contains the option texts, so `getByLabel(exact)` misses it;
 * the role query by accessible name does not.
 */
export function labelledControl(scope: Page | Locator, label: string): Locator {
  return scope
    .getByRole("combobox", { name: label, exact: true })
    .or(scope.getByRole("textbox", { name: label, exact: true }))
    .or(scope.getByRole("spinbutton", { name: label, exact: true }))
    .or(scope.getByLabel(label, { exact: true }))
    .first()
}

/**
 * Choose one option of a labelled control: a native select by option label
 * (then by value), otherwise a combobox opened by click.
 */
export async function chooseOption(scope: Page | Locator, label: string, option: string): Promise<void> {
  const control = labelledControl(scope, label)
  await expect(control).toBeVisible()
  const tag = await control.evaluate((el) => el.tagName.toLowerCase())
  if (tag === "select") {
    const values = await control.evaluate((el) =>
      Array.from((el as HTMLSelectElement).options).map((o) => ({ label: o.label.trim(), value: o.value }))
    )
    const byLabel = values.find((o) => o.label === option)
    const byValue = values.find((o) => o.value === option)
    const loose = values.find((o) => o.label.toLowerCase() === option.toLowerCase())
    const chosen = byLabel ?? byValue ?? loose
    if (chosen === undefined) throw new Error(`no option ${option} in ${label}: ${JSON.stringify(values)}`)
    await control.selectOption(chosen.value)
    return
  }
  await control.click()
  const page = "page" in scope ? scope.page() : scope
  await page.getByRole("option", { name: option, exact: true }).click()
}

/** Fill a labelled text or number input, or choose a select option. */
export async function fillField(scope: Page | Locator, label: string, value: string): Promise<void> {
  const control = labelledControl(scope, label)
  await expect(control).toBeVisible()
  const tag = await control.evaluate((el) => el.tagName.toLowerCase())
  const role = await control.getAttribute("role")
  if (tag === "select" || role === "combobox") {
    await chooseOption(scope, label, value)
    return
  }
  await control.fill(value)
}

/** The write-only secret input with this accessible label. */
export function secretInput(scope: Page | Locator, label: string): Locator {
  const page = "page" in scope ? scope.page() : scope
  return scope.getByLabel(label, { exact: true }).and(page.locator('input[type="password"]'))
}

/** Assert the write-only secret input contract before typing into it. */
export async function expectWriteOnlySecretInput(input: Locator): Promise<void> {
  await expect(input).toHaveCount(1)
  await expect(input).toHaveAttribute("type", "password")
  await expect(input).toHaveAttribute("autocomplete", "off")
  await expect(input).toHaveValue("")
}

/** Click a confirm button when a confirmation dialog appears. */
export async function confirmIfAsked(page: Page, name: string): Promise<void> {
  const button = page.getByRole("dialog").getByRole("button", { name, exact: true })
  try {
    await button.waitFor({ state: "visible", timeout: 2_000 })
  } catch {
    return
  }
  await button.click()
}
