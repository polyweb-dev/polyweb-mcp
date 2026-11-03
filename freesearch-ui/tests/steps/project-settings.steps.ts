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

Given("the system requires strict redaction", async () => {
  setSystemTraceDefault("payload_redaction", "strict")
})

Then(
  "the settings field {string} shows {string}",
  async ({ page }, fieldId: string, text: string) => {
    await expect(fieldRow(page, fieldId)).toContainText(text, { timeout: 15_000 })
  }
)

Then("the trace policy summary reads {string}", async ({ page }, text: string) => {
  await expect(page.getByTestId("trace-policy-summary")).toHaveText(text, { timeout: 15_000 })
})

Then(
  "the {string} option {string} is disabled with {string}",
  async ({ page }, fieldLabel: string, option: string, reason: string) => {
    const fieldIds: Record<string, string> = {
      "Payload detail": "trace.detail",
      Redaction: "trace.payload_redaction",
    }
    const row = fieldRow(page, fieldIds[fieldLabel] ?? fieldLabel)
    const control = row
      .getByRole("radio", { name: option, exact: true })
      .or(row.getByRole("option", { name: option, exact: true }))
    await expect(control.first()).toBeDisabled({ timeout: 15_000 })
    await expect(row).toContainText(reason)
  }
)

When(
  "I set the settings field {string} labelled {string} to {string}",
  async ({ page }, fieldId: string, label: string, value: string) => {
    await fillField(fieldRow(page, fieldId), label, value)
  }
)

When("I inherit the settings field {string}", async ({ page }, label: string) => {
  await page.getByRole("button", { name: `Inherit ${label}`, exact: true }).click()
})

When("I save the {string} settings section", async ({ page }, section: string) => {
  await page.getByRole("button", { name: `Save ${section}`, exact: true }).click()
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
  await expect(page.getByRole("button", { name: /^Save / })).toHaveCount(0)
  await expect(page.getByRole("button", { name: /^Inherit / })).toHaveCount(0)
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

Then("the copy Apply button is {word}", async ({ page }, stateWord: string) => {
  const apply = copyDialog(page).getByRole("button", { name: "Apply copy", exact: true })
  if (stateWord === "disabled") await expect(apply).toBeDisabled()
  else await expect(apply).toBeEnabled()
})

When("I choose {string} as the copy source", async ({ page }, project: string) => {
  await chooseOption(copyDialog(page), "Source project", project)
})

When("I choose the copy mode {string}", async ({ page }, mode: string) => {
  await copyDialog(page).getByRole("radio", { name: mode, exact: true }).check()
})

When("I preview the copy", async ({ page }) => {
  const dialog = copyDialog(page)
  await expect(dialog.getByRole("radio", { name: "Overrides only", exact: true })).toBeVisible()
  const response = page.waitForResponse(
    (res) => PREVIEW_PATH.test(new URL(res.url()).pathname) && res.request().method() === "POST"
  )
  await dialog.getByRole("button", { name: "Preview", exact: true }).click()
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
  const box = page.getByTestId("copy-preview").getByRole("checkbox", { name: `Copy binding ${routeLabel}`, exact: true })
  await expect(box).toBeEnabled()
})

Then(
  "the copy preview refuses the binding {string} with {string}",
  async ({ page }, routeLabel: string, reason: string) => {
    const preview = page.getByTestId("copy-preview")
    await expect(preview.getByRole("checkbox", { name: `Copy binding ${routeLabel}`, exact: true })).toBeDisabled()
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
  const boxes = page.getByTestId("copy-preview").getByRole("checkbox", { name: /^Copy binding / })
  const checked: string[] = []
  const count = await boxes.count()
  for (let index = 0; index < count; index += 1) {
    const box = boxes.nth(index)
    if ((await box.isEnabled()) && (await box.isChecked())) {
      const name = (await box.getAttribute("aria-label")) ?? (await box.evaluate((el) => (el as HTMLInputElement).labels?.[0]?.textContent ?? ""))
      checked.push(name.replace(/^Copy binding /, "").trim())
    }
  }
  copyEvidence.checkedBindings = checked
  await dialog.getByRole("button", { name: "Apply copy", exact: true }).click()
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
