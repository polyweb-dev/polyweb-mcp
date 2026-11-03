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
  "trace.retention_days": { value: 90, systemDefault: 30, override: 120, provenance: "system_constrained" as const, limit: 90, constraintApplied: true },
  "trace.sampling_rate": { value: 0.25, systemDefault: 1, override: 0.25 },
  "trace.payload_redaction": { value: "strict", limit: "strict" },
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
  it("shows sections, provenance, system default and limit", async () => {
    installSettingsStub()
    renderInProject(<ProjectSettingsPage accountId="acc" />)
    expect(await screen.findByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument()
    for (const name of ["Routing", "Execution", "Trace policy"]) {
      expect(await screen.findByRole("heading", { level: 2, name })).toBeInTheDocument()
    }
    const attempts = screen.getByTestId("settings-field-routing.max_attempts")
    expect(within(attempts).getByText("Project override")).toBeInTheDocument()
    expect(within(attempts).getByText("System default: 3")).toBeInTheDocument()
    const retention = screen.getByTestId("settings-field-trace.retention_days")
    expect(within(retention).getByText("Limited by system")).toBeInTheDocument()
    expect(within(retention).getByText("System limit: 90")).toBeInTheDocument()
    expect(within(retention).getByText("Your override exceeds the system limit; the system limit applies.")).toBeInTheDocument()
    expect(within(screen.getByTestId("settings-field-routing.fallback_policy")).getByText("System default")).toBeInTheDocument()
    expect(screen.queryByTestId("settings-field-system.max_trace_retention_days")).toBeNull()
  })

  it("summarizes the trace policy and limits looser options", async () => {
    installSettingsStub()
    renderInProject(<ProjectSettingsPage accountId="acc" />)
    expect(await screen.findByTestId("trace-policy-summary")).toHaveTextContent(
      "New traces: 25% sampled, Metadata only, Strict redaction, kept 90 days."
    )
    expect(screen.getByRole("option", { name: "Full payloads" })).toBeDisabled()
    expect(screen.getByText("The system allows metadata only.")).toBeInTheDocument()
    expect(screen.getByRole("option", { name: "Standard" })).toBeDisabled()
    expect(screen.getByText("The system requires strict redaction.")).toBeInTheDocument()
    expect(screen.getByRole("spinbutton", { name: "Retention (days)" })).toHaveAttribute("max", "90")
  })

  it("is read-only without settings.write", async () => {
    installSettingsStub({ permissions: PROJECT_MEMBER_PERMISSIONS })
    renderInProject(<ProjectSettingsPage accountId="acc" />)
    expect(await screen.findByText("You can view these settings. Ask a project administrator to change them.")).toBeInTheDocument()
    await screen.findByTestId("settings-field-routing.max_attempts")
    expect(screen.queryByRole("button", { name: /^Save / })).toBeNull()
    expect(screen.queryByRole("button", { name: /^Inherit / })).toBeNull()
    expect(screen.queryByRole("spinbutton")).toBeNull()
    expect(screen.queryByRole("button", { name: "Copy from another project" })).toBeNull()
  })

  it("shows Set by system for a field without override", async () => {
    installWorkspaceStub((req) =>
      req.url === SETTINGS_URL
        ? ok(settingsResolutionFixture({ projectId: PROJECT_ALPHA_ID, seeds: { "routing.max_attempts": { value: 3, overrideAllowed: false } } }))
        : err(404, null)
    )
    renderInProject(<ProjectSettingsPage accountId="acc" />)
    const row = await screen.findByTestId("settings-field-routing.max_attempts")
    expect(within(row).getByText("Set by system")).toBeInTheDocument()
    expect(within(row).queryByRole("spinbutton")).toBeNull()
  })
})

describe("ProjectSettingsPage editing", () => {
  it("sends only the changed fields of one section at the expected revision", async () => {
    const stub = installSettingsStub()
    const user = userEvent.setup()
    renderInProject(<ProjectSettingsPage accountId="acc" />)
    const save = await screen.findByRole("button", { name: "Save Trace policy" })
    expect(save).toBeDisabled()
    const retention = screen.getByRole("spinbutton", { name: "Retention (days)" })
    await user.clear(retention)
    await user.type(retention, "60")
    await user.click(save)
    expect(await screen.findByText("Settings saved.")).toBeInTheDocument()
    const put = stub.requests.find((req) => req.method === "PUT")
    expect(put?.body).toEqual({ expected_revision: 4, trace: { retention_days: 60 } })
  })

  it("Inherit sends null for that field", async () => {
    const stub = installSettingsStub()
    const user = userEvent.setup()
    renderInProject(<ProjectSettingsPage accountId="acc" />)
    await user.click(await screen.findByRole("button", { name: "Inherit Max attempts" }))
    expect(screen.getByText("Inherits the system default after saving.")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Save Routing" }))
    await screen.findByText("Settings saved.")
    expect(stub.requests.find((req) => req.method === "PUT")?.body).toEqual({ expected_revision: 4, routing: { max_attempts: null } })
  })

  it("asks for a reload on a stale revision", async () => {
    const stub = installSettingsStub({ onPut: () => err(409, { detail: { code: "SETTINGS_REVISION_CONFLICT", message: "stale" } }) })
    const user = userEvent.setup()
    renderInProject(<ProjectSettingsPage accountId="acc" />)
    await user.click(await screen.findByRole("checkbox", { name: "Cache" }))
    await user.click(screen.getByRole("button", { name: "Save Execution" }))
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
    await user.click(await screen.findByRole("button", { name: "Copy from another project" }))
    expect(await screen.findByRole("dialog", { name: "Copy settings" })).toBeInTheDocument()
  })
})
