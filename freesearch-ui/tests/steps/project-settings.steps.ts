import { expect } from "@playwright/test"
import type { Locator, Page } from "@playwright/test"
import { Given, Then, When } from "./fixtures"
import { projectStubId } from "./projectStub"
import {
  SEED,
  changeProjectSettingsElsewhere,
  configRequests,
  projectOverrides,
  projectSettingsRevision,
  setSystemTraceDefault,
} from "./providerConfigStub"
import { chooseOption, fillField } from "./providerConfigUi"

/**
 * Project Settings page and the Copy settings dialog (U3 contract). Field
 * rows carry data-testid="settings-field-<field_id>"; the copy preview lives
 * in data-testid="copy-preview".
 */

function fieldRow(page: Page, fieldId: string): Locator {
  return page.getByTestId(`settings-field-${fieldId}`)
}

function copyDialog(page: Page): Locator {
  return page.getByRole("dialog", { name: "Copy settings", exact: true })
}

const SETTINGS_PATH = /^\/api\/v1\/projects\/[0-9a-f-]{36}\/settings$/
const PREVIEW_PATH = /\/settings\/copy\/preview$/
const APPLY_PATH = /\/settings\/copy$/

/** The last preview response and the binding selection at apply time. */
const copyEvidence: {
  preview: Record<string, unknown> | null
  checkedBindings: string[] | null
  settingsReadsBeforeReload: number
} = { preview: null, checkedBindings: null, settingsReadsBeforeReload: 0 }

Given("the system limits traces to metadata", async () => {
  setSystemTraceDefault("detail", "metadata")
})

Then(
  "the settings field {string} shows {string}",
  async ({ page }, fieldId: string, text: string) => {
    await expect(fieldRow(page, fieldId)).toContainText(text, { timeout: 15_000 })
  }
)

Then(
  "the settings field {string} does not show {string}",
  async ({ page }, fieldId: string, text: string) => {
    const row = fieldRow(page, fieldId)
    await expect(row).toBeVisible({ timeout: 15_000 })
    await expect(row).not.toContainText(text)
  }
)

Then("the settings page shows no field {string}", async ({ page }, fieldId: string) => {
  await expect(page.getByTestId(/^settings-field-/).first()).toBeVisible({ timeout: 15_000 })
  await expect(fieldRow(page, fieldId)).toHaveCount(0)
})

Then(
  "the {string} option {string} is disabled with {string}",
  async ({ page }, fieldLabel: string, option: string, reason: string) => {
    const fieldIds: Record<string, string> = {
      "Payload detail": "trace.detail",
    }
    const row = fieldRow(page, fieldIds[fieldLabel] ?? fieldLabel)
    await row.getByRole("combobox", { name: fieldLabel, exact: true }).click({ timeout: 15_000 })
    const control = row.getByRole("option", { name: new RegExp(`^${option}`) })
    await expect(control.first()).toHaveAttribute("aria-disabled", "true")
    await expect(row).toContainText(reason)
    await page.keyboard.press("Escape")
  }
)

When(
  "I set the settings field {string} labelled {string} to {string}",
  async ({ page }, fieldId: string, label: string, value: string) => {
    await fillField(fieldRow(page, fieldId), label, value)
  }
)

When("I inherit the settings field {string}", async ({ page }, label: string) => {
  await page.getByRole("button", { name: `Reset ${label}`, exact: true }).click()
})

When("I turn off trace deletion", async ({ page }) => {
  await page.getByRole("switch", { name: "Delete traces older than" }).click()
})

Then("trace deletion is off", async ({ page }) => {
  await expect(page.getByRole("switch", { name: "Delete traces older than" })).toHaveAttribute("aria-checked", "false")
})

When("I save the settings", async ({ page }) => {
  await page.getByRole("button", { name: "Save changes", exact: true }).click()
})

Then("the last settings save sent exactly:", async ({}, doc: string) => {
  const expected = JSON.parse(doc) as Record<string, unknown>
  await expect
    .poll(() => {
      const puts = configRequests("PUT", SETTINGS_PATH)
      return puts.length > 0 ? puts[puts.length - 1].body?.expected_revision : undefined
    })
    .toBe(expected.expected_revision)
  const puts = configRequests("PUT", SETTINGS_PATH)
  expect(puts[puts.length - 1].body).toEqual(expected)
})

When("project {word} settings change elsewhere", async ({ page }, name: string) => {
  // The page (and any open preview) has read the current revision first.
  await expect.poll(() => configRequests("GET", SETTINGS_PATH).length).toBeGreaterThan(0)
  // An open dialog hides the page from the accessibility tree, so wait for
  // the rendered settings in the DOM, not for a visible heading.
  await expect(page.getByTestId("settings-field-trace.retention_days")).toBeAttached({ timeout: 15_000 })
  changeProjectSettingsElsewhere(projectStubId(name))
})

When("I reload the settings", async ({ page }) => {
  copyEvidence.settingsReadsBeforeReload = configRequests("GET", SETTINGS_PATH).length
  await page.getByRole("button", { name: "Reload settings", exact: true }).click()
})

Then("the settings were read again", async () => {
  await expect
    .poll(() => configRequests("GET", SETTINGS_PATH).length)
    .toBeGreaterThan(copyEvidence.settingsReadsBeforeReload)
})

Then("the settings page offers no editing controls", async ({ page }) => {
  await expect(page.getByTestId(/^settings-field-/).first()).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole("button", { name: "Save changes", exact: true })).toHaveCount(0)
  await expect(page.getByRole("button", { name: /^Reset / })).toHaveCount(0)
  await expect(page.getByRole("button", { name: "Copy from another project", exact: true })).toHaveCount(0)
  const rows = page.getByTestId(/^settings-field-/)
  const editable = rows.locator(
    "input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [role='switch']:not([aria-disabled='true']):not([disabled]), [role='combobox']:not([aria-disabled='true'])"
  )
  await expect(editable).toHaveCount(0)
})

// --- Copy settings ---------------------------------------------------------

When("I open the copy settings dialog", async ({ page }) => {
  copyEvidence.preview = null
  copyEvidence.checkedBindings = null
  await page.getByRole("button", { name: "Copy from another project", exact: true }).click({ timeout: 15_000 })
  await expect(copyDialog(page)).toBeVisible()
})

Then("the copy dialog offers {string}", async ({ page }, action: string) => {
  const dialog = copyDialog(page)
  const other = action === "Apply changes" ? "Preview changes" : "Apply changes"
  await expect(dialog.getByRole("button", { name: action, exact: true })).toBeVisible()
  await expect(dialog.getByRole("button", { name: other, exact: true })).toHaveCount(0)
  if (action === "Apply changes") await expect(dialog.getByRole("button", { name: action, exact: true })).toBeEnabled()
})

When("I choose {string} as the copy source", async ({ page }, project: string) => {
  await chooseOption(copyDialog(page), "Source project", project)
})

When("I choose the copy mode {string}", async ({ page }, mode: string) => {
  await copyDialog(page).getByRole("group", { name: "Copy mode", exact: true }).getByRole("button", { name: mode, exact: true }).click()
})

When("I preview the copy", async ({ page }) => {
  const dialog = copyDialog(page)
  await expect(dialog.getByRole("button", { name: "Changed values", exact: true })).toBeVisible()
  const response = page.waitForResponse(
    (res) => PREVIEW_PATH.test(new URL(res.url()).pathname) && res.request().method() === "POST"
  )
  await dialog.getByRole("button", { name: "Preview changes", exact: true }).click()
  const answered = await response
  if (answered.status() === 200) copyEvidence.preview = (await answered.json()) as Record<string, unknown>
  await expect(page.getByTestId("copy-preview")).toBeVisible()
})

Then(
  "the copy preview lists {string} as {string}",
  async ({ page }, field: string, change: string) => {
    const row = page.getByTestId("copy-preview").getByRole("row").filter({ hasText: field })
    await expect(row).toHaveCount(1)
    await expect(row).toContainText(change)
  }
)

Then("the copy preview offers the binding {string}", async ({ page }, routeLabel: string) => {
  const box = page.getByTestId("copy-preview").getByRole("checkbox", { name: routeLabel, exact: true })
  await expect(box).toBeEnabled()
})

Then(
  "the copy preview refuses the binding {string} with {string}",
  async ({ page }, routeLabel: string, reason: string) => {
    const preview = page.getByTestId("copy-preview")
    await expect(preview.getByRole("checkbox", { name: new RegExp(`^${routeLabel}`) })).toBeDisabled()
    await expect(preview).toContainText(reason)
  }
)

Then("the copy preview wrote nothing to project {word}", async ({}, name: string) => {
  expect(configRequests("POST", PREVIEW_PATH).length).toBeGreaterThan(0)
  expect(configRequests("POST", APPLY_PATH)).toHaveLength(0)
  expect(configRequests("PUT", SETTINGS_PATH)).toHaveLength(0)
  expect(projectSettingsRevision(projectStubId(name))).toBe(2)
  expect(projectOverrides(projectStubId(name))).not.toHaveProperty(["routing.fallback_policy"])
})

When("I apply the copy", async ({ page }) => {
  const dialog = copyDialog(page)
  const boxes = page.getByTestId("copy-preview").getByRole("checkbox")
  const checked: string[] = []
  const count = await boxes.count()
  for (let index = 0; index < count; index += 1) {
    const box = boxes.nth(index)
    if ((await box.isEnabled()) && (await box.isChecked())) {
      const name = await box.evaluate((el) => (el as HTMLButtonElement).labels?.[0]?.textContent ?? "")
      checked.push(name.trim())
    }
  }
  copyEvidence.checkedBindings = checked
  await dialog.getByRole("button", { name: "Apply changes", exact: true }).click()
})

Then("the apply request echoed the preview revisions and the selected bindings", async () => {
  await expect.poll(() => configRequests("POST", APPLY_PATH).length).toBe(1)
  const body = configRequests("POST", APPLY_PATH)[0].body ?? {}
  const preview = copyEvidence.preview
  expect(preview).not.toBeNull()
  expect(body.source_project_id).toBe(preview?.source_project_id)
  expect(body.expected_source_revision).toBe(preview?.source_revision)
  expect(body.expected_target_revision).toBe(preview?.target_revision)
  expect(body.expected_system_revision).toBe(preview?.system_revision)
  expect(body.mode ?? "overrides_only").toBe(preview?.mode)
  const versions = (body.binding_versions ?? {}) as Record<string, number>
  // Only selected eligible bindings, each at the preview's version.
  expect(versions).not.toHaveProperty(SEED.betaPrivateBinding)
  const expected: Record<string, number> = {}
  if ((copyEvidence.checkedBindings ?? []).includes("beta-brave")) expected[SEED.betaBraveBinding] = 3
  expect(versions).toEqual(expected)
})

Then("the copy preview is cleared", async ({ page }) => {
  await expect(page.getByTestId("copy-preview")).toHaveCount(0)
})

Then(
  "project {word} now overrides {string} with {string}",
  async ({}, name: string, fieldId: string, value: string) => {
    await expect.poll(() => projectOverrides(projectStubId(name))[fieldId]).toBe(value)
  }
)

Then("project {word} does not override {string}", async ({}, name: string, fieldId: string) => {
  await expect.poll(() => configRequests("POST", APPLY_PATH).length).toBeGreaterThan(0)
  expect(projectOverrides(projectStubId(name))).not.toHaveProperty([fieldId])
})
