import { afterEach, describe, expect, it, vi } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { err, ok } from "@/test/fetchMock"
import type { RecordedRequest } from "@/test/fetchMock"
import { PROJECT_ALPHA_ID, PROJECT_MEMBER_PERMISSIONS } from "@/test/accessFixtures"
import { settingsResolutionFixture } from "@/test/settingsFixtures"
import { installWorkspaceStub, renderInProject } from "@/test/workspaceHarness"
import { ProjectSettingsPage } from "./ProjectSettingsPage"

const SETTINGS_URL = `/api/v1/projects/${PROJECT_ALPHA_ID}/settings`

const SEEDS = {
  "routing.max_attempts": { value: 5, systemDefault: 3, override: 5 },
  "trace.retention_days": { value: 90, systemDefault: null, override: 120, provenance: "system_constrained" as const, limit: 90, constraintApplied: true },
}

function installSettingsStub(options: { permissions?: readonly string[]; onPut?: (req: RecordedRequest) => Response } = {}) {
  return installWorkspaceStub(
    (req) => {
      if (req.method === "GET" && req.url === SETTINGS_URL) {
        return ok(settingsResolutionFixture({ projectId: PROJECT_ALPHA_ID, seeds: SEEDS }))
      }
      if (req.method === "PUT" && req.url === SETTINGS_URL) {
        return options.onPut?.(req) ?? ok(settingsResolutionFixture({ projectId: PROJECT_ALPHA_ID, projectRevision: 5 }))
      }
      return err(404, null)
    },
    options.permissions === undefined ? {} : { projectPermissions: options.permissions }
  )
}

afterEach(() => vi.unstubAllGlobals())

describe("ProjectSettingsPage view", () => {
  it("shows only the applied Trace policy section, with a hint only on overridden rows", async () => {
    installSettingsStub()
    renderInProject(<ProjectSettingsPage accountId="acc" />)
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument()
    expect(await screen.findByRole("heading", { level: 3, name: "Trace policy" })).toBeInTheDocument()
    const retention = screen.getByTestId("settings-field-trace.retention_days")
    expect(screen.getByText("API keys, auth headers, cookies, passwords and tokens are always removed from traces")).toBeInTheDocument()
    expect(within(retention).getByText("The system can delete traces after this limit")).toBeInTheDocument()
    expect(within(retention).getByText("Your override exceeds the system limit. The system limit applies")).toBeInTheDocument()
    expect(within(screen.getByTestId("settings-field-trace.detail")).queryByText(/System default/)).toBeNull()
    expect(screen.queryByText(/System default/)).toBeNull()
    expect(screen.queryByTestId("settings-field-system.max_trace_retention_days")).toBeNull()
  })

  it("hides the routing and execution settings that calls do not use", async () => {
    installSettingsStub()
    renderInProject(<ProjectSettingsPage accountId="acc" />)
    await screen.findByTestId("settings-field-trace.retention_days")
    for (const name of ["Routing", "Execution"]) {
      expect(screen.queryByRole("heading", { level: 3, name })).toBeNull()
    }
    expect(screen.queryByTestId("settings-field-routing.max_attempts")).toBeNull()
    expect(screen.queryByTestId("settings-field-execution.cache_enabled")).toBeNull()
    expect(screen.queryByText("Not applied yet")).toBeNull()
  })

  it("shows the payload choice and the retention ceiling", async () => {
    installSettingsStub()
    const user = userEvent.setup()
    renderInProject(<ProjectSettingsPage accountId="acc" />)
    await screen.findByTestId("settings-field-trace.detail")
    expect(screen.queryByTestId("trace-policy-summary")).toBeNull()
    expect(screen.queryByText(/New traces:/)).toBeNull()
    await user.click(screen.getByRole("combobox", { name: "Payload detail" }))
    expect(screen.getByRole("option", { name: "Full requests" })).toBeInTheDocument()
    await user.keyboard("{Escape}")
    const days = screen.getByRole("spinbutton", { name: "Days" })
    await user.clear(days)
    await user.type(days, "91")
    expect(days).toHaveAttribute("aria-invalid", "true")
    expect(screen.getByText("Enter a whole number from 1 to 90")).toBeInTheDocument()
  })

  it("shows secret removal help without sampling or redaction controls", async () => {
    installSettingsStub()
    renderInProject(<ProjectSettingsPage accountId="acc" />)
    expect(await screen.findByText(/API keys, auth headers, cookies, passwords and tokens/)).toBeInTheDocument()
    expect(screen.queryByText("Sampling rate")).toBeNull()
    expect(screen.queryByText("Redaction")).toBeNull()
  })

  it("starts with full requests and keeps every trace by default", async () => {
    installWorkspaceStub((req) =>
      req.url === SETTINGS_URL ? ok(settingsResolutionFixture({ projectId: PROJECT_ALPHA_ID })) : err(404, null)
    )
    const user = userEvent.setup()
    renderInProject(<ProjectSettingsPage accountId="acc" />)
    expect(await screen.findByText("Traces stay until you delete them")).toBeInTheDocument()
    expect(screen.getByRole("switch", { name: "Delete old traces" })).not.toBeChecked()
    await user.click(screen.getByRole("switch", { name: "Delete old traces" }))
    expect(screen.getByText("after")).toBeInTheDocument()
    expect(screen.getByRole("spinbutton", { name: "Days" })).toHaveValue(30)
  })

  it("shows a neutral note for an explicit metadata ceiling", async () => {
    installWorkspaceStub((req) =>
      req.url === SETTINGS_URL
        ? ok(settingsResolutionFixture({ projectId: PROJECT_ALPHA_ID, seeds: { "trace.detail": { value: "metadata", limit: "metadata" } } }))
        : err(404, null)
    )
    renderInProject(<ProjectSettingsPage accountId="acc" />)
    expect(await screen.findByText("The system limit is metadata only")).toBeInTheDocument()
    expect(screen.queryByRole("combobox", { name: "Payload detail" })).toBeNull()
  })

  it("is read-only without settings.write", async () => {
    installSettingsStub({ permissions: PROJECT_MEMBER_PERMISSIONS })
    renderInProject(<ProjectSettingsPage accountId="acc" />)
    expect(await screen.findByText("Ask a project admin to change this")).toBeInTheDocument()
    await screen.findByTestId("settings-field-trace.retention_days")
    expect(screen.queryByRole("button", { name: "Save changes" })).toBeNull()
    expect(screen.queryByRole("button", { name: /^Reset / })).toBeNull()
    expect(screen.queryByRole("spinbutton")).toBeNull()
    expect(screen.queryByRole("combobox")).toBeNull()
    expect(screen.queryByRole("button", { name: "Copy from another project" })).toBeNull()
    expect(within(screen.getByTestId("settings-field-trace.retention_days")).getByText("90")).toBeInTheDocument()
  })

  it("shows Set by system for a field without override", async () => {
    installWorkspaceStub((req) =>
      req.url === SETTINGS_URL
        ? ok(settingsResolutionFixture({ projectId: PROJECT_ALPHA_ID, seeds: { "trace.retention_days": { value: 30, overrideAllowed: false } } }))
        : err(404, null)
    )
    renderInProject(<ProjectSettingsPage accountId="acc" />)
    const row = await screen.findByTestId("settings-field-trace.retention_days")
    expect(within(row).getByText("30")).toBeInTheDocument()
    expect(within(row).queryByRole("spinbutton")).toBeNull()
  })
})

describe("ProjectSettingsPage editing", () => {
  it("shows one save bar only once something changed and sends only the changed fields", async () => {
    const stub = installSettingsStub()
    const user = userEvent.setup()
    renderInProject(<ProjectSettingsPage accountId="acc" />)
    const retention = await screen.findByRole("spinbutton", { name: "Days" })
    expect(screen.queryByRole("button", { name: "Save changes" })).toBeNull()
    await user.clear(retention)
    await user.type(retention, "60")
    await user.click(screen.getByRole("combobox", { name: "Payload detail" }))
    await user.keyboard("{Escape}")
    expect(screen.getByText("1 unsaved change")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Save changes" }))
    expect(await screen.findByText("Settings saved")).toBeInTheDocument()
    const put = stub.requests.find((req) => req.method === "PUT")
    expect(put?.body).toEqual({ expected_revision: 4, trace: { retention_days: 60 } })
    expect(screen.queryByRole("button", { name: "Save changes" })).toBeNull()
  })

  it("shows the allowed range under an invalid number and refuses to save it", async () => {
    const stub = installSettingsStub()
    const user = userEvent.setup()
    renderInProject(<ProjectSettingsPage accountId="acc" />)
    const retention = await screen.findByRole("spinbutton", { name: "Days" })
    await user.clear(retention)
    await user.type(retention, "400")
    expect(screen.getByText("Enter a whole number from 1 to 90")).toBeInTheDocument()
    expect(retention).toHaveAttribute("aria-invalid", "true")
    expect(screen.getByText("1 field to fix")).toBeInTheDocument()
    const save = screen.getByRole("button", { name: "Save changes" })
    expect(save).toBeEnabled()
    await user.click(save)
    expect(screen.getByText("Fix the highlighted fields before saving")).toBeInTheDocument()
    expect(stub.requests.filter((req) => req.method === "PUT")).toHaveLength(0)
    await user.click(screen.getByRole("button", { name: "Discard" }))
    expect(screen.queryByText("Enter a whole number from 1 to 90")).toBeNull()
    expect(screen.queryByRole("button", { name: "Save changes" })).toBeNull()
  })

  it("stores the selected metadata detail", async () => {
    const stub = installSettingsStub()
    const user = userEvent.setup()
    renderInProject(<ProjectSettingsPage accountId="acc" />)
    await user.click(await screen.findByRole("combobox", { name: "Payload detail" }))
    await user.click(screen.getByRole("option", { name: "Metadata only" }))
    await user.click(screen.getByRole("button", { name: "Save changes" }))
    await screen.findByText("Settings saved")
    expect(stub.requests.find((req) => req.method === "PUT")?.body).toEqual({ expected_revision: 4, trace: { detail: "metadata" } })
  })

  it("turning retention off sends null", async () => {
    const stub = installSettingsStub()
    const user = userEvent.setup()
    renderInProject(<ProjectSettingsPage accountId="acc" />)
    const toggle = await screen.findByRole("switch", { name: "Delete old traces" })
    await user.click(toggle)
    expect(screen.getByText("Traces stay until you delete them")).toBeInTheDocument()
    expect(screen.getByText("1 unsaved change")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Save changes" }))
    await screen.findByText("Settings saved")
    expect(stub.requests.find((req) => req.method === "PUT")?.body).toEqual({ expected_revision: 4, trace: { retention_days: null } })
  })

  it("Discard drops the draft without a write", async () => {
    const stub = installSettingsStub()
    const user = userEvent.setup()
    renderInProject(<ProjectSettingsPage accountId="acc" />)
    const retention = await screen.findByRole("spinbutton", { name: "Days" })
    await user.clear(retention)
    await user.type(retention, "60")
    await user.click(screen.getByRole("button", { name: "Discard" }))
    expect(screen.queryByRole("button", { name: "Save changes" })).toBeNull()
    expect(screen.getByRole("spinbutton", { name: "Days" })).toHaveValue(90)
    expect(stub.requests.filter((req) => req.method === "PUT")).toHaveLength(0)
  })

  it("asks for a reload on a stale revision", async () => {
    const stub = installSettingsStub({ onPut: () => err(409, { detail: { code: "SETTINGS_REVISION_CONFLICT", message: "stale" } }) })
    const user = userEvent.setup()
    renderInProject(<ProjectSettingsPage accountId="acc" />)
    const retention = await screen.findByRole("spinbutton", { name: "Days" })
    await user.clear(retention)
    await user.type(retention, "60")
    await user.click(screen.getByRole("button", { name: "Save changes" }))
    expect(await screen.findByText("Settings changed since you opened them.")).toBeInTheDocument()
    const gets = stub.requestsTo(SETTINGS_URL).filter((req) => req.method === "GET").length
    await user.click(screen.getByRole("button", { name: "Reload settings" }))
    await waitFor(() => expect(stub.requestsTo(SETTINGS_URL).filter((req) => req.method === "GET").length).toBe(gets + 1))
    await waitFor(() => expect(screen.queryByText("Settings changed since you opened them.")).toBeNull())
  })

  it("offers Copy from another project with settings.copy and settings.write", async () => {
    installSettingsStub()
    const user = userEvent.setup()
    renderInProject(<ProjectSettingsPage accountId="acc" />)
    const copy = await screen.findByRole("button", { name: "Copy from another project" })
    expect(copy).toHaveClass("h-6")
    expect(copy).not.toHaveClass("bg-primary")
    await user.click(copy)
    expect(await screen.findByRole("dialog", { name: "Copy settings" })).toBeInTheDocument()
  })
})
