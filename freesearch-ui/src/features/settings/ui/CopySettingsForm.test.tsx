import { afterEach, describe, expect, it, vi } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { UserEvent } from "@testing-library/user-event"
import { err, ok } from "@/test/fetchMock"
import type { RecordedRequest } from "@/test/fetchMock"
import { PROJECT_ALPHA_ID, PROJECT_BETA_ID, projectFixture } from "@/test/accessFixtures"
import { settingsResolutionFixture } from "@/test/settingsFixtures"
import { installWorkspaceStub, renderInProject } from "@/test/workspaceHarness"
import { CopySettingsForm } from "./CopySettingsForm"

const TARGET = PROJECT_ALPHA_ID
const SOURCE = PROJECT_BETA_ID
const PREVIEW_URL = `/api/v1/projects/${TARGET}/settings/copy/preview`
const APPLY_URL = `/api/v1/projects/${TARGET}/settings/copy`
const SOURCES = [projectFixture({ id: SOURCE, name: "Beta", slug: "beta" })]

function plan(request: RecordedRequest) {
  const body = request.body as { mode: string; binding_versions: Record<string, number> }
  return {
    source_project_id: SOURCE,
    target_project_id: TARGET,
    mode: body.mode,
    source_revision: 7,
    target_revision: 4,
    system_revision: 2,
    overrides: {},
    effective_snapshot: {},
    fields: [{ field_id: "routing.max_attempts", section: "routing", attribute: "max_attempts", provenance: "project_override", value: 6, changed: true }],
    rejected: [{ field_id: "trace.detail", reason: "The target system allows metadata only." }],
    bindings: [
      { binding_id: "b1", credential_id: "c1", route_label: "primary", version: 3, selected: "b1" in body.binding_versions, eligible: true, rejection: null },
      { binding_id: "b2", credential_id: "c2", route_label: "private", version: 1, selected: false, eligible: false, rejection: "The credential is not granted to this project." },
    ],
    target: settingsResolutionFixture({ projectId: TARGET }),
  }
}

function installCopyStub(onApply?: (req: RecordedRequest) => Response | null) {
  return installWorkspaceStub(
    (req) => {
      if (req.method === "GET" && req.url === `/api/v1/projects/${SOURCE}/settings`) {
        return ok(settingsResolutionFixture({ projectId: SOURCE, projectRevision: 7, systemRevision: 2 }))
      }
      if (req.method === "GET" && req.url === `/api/v1/projects/${TARGET}/settings`) {
        return ok(settingsResolutionFixture({ projectId: TARGET, projectRevision: 4, systemRevision: 2 }))
      }
      if (req.method === "POST" && req.url === PREVIEW_URL) return ok(plan(req))
      if (req.method === "POST" && req.url === APPLY_URL) {
        return onApply?.(req) ?? ok({ ...plan(req), target_revision: 5, bindings_copied: ["nb1"], audit_event_id: "a1", target: settingsResolutionFixture({ projectId: TARGET, projectRevision: 5 }) })
      }
      return err(404, null)
    },
    { projects: [projectFixture(), ...SOURCES] }
  )
}

function renderForm(onApplied = vi.fn(), onClose = vi.fn()) {
  renderInProject(<CopySettingsForm target={{ projectId: TARGET, onApplied }} sources={SOURCES} onClose={onClose} />)
  return { onApplied, onClose }
}

async function chooseSource(user: UserEvent) {
  await user.click(screen.getByLabelText("Source project"))
  await user.click(screen.getByRole("option", { name: "Beta" }))
}

async function preview(user: UserEvent) {
  await chooseSource(user)
  await user.click(screen.getByRole("button", { name: "Preview changes" }))
  return screen.findByTestId("copy-preview")
}

afterEach(() => vi.unstubAllGlobals())

describe("CopySettingsForm", () => {
  it("disables Apply until a preview exists and writes nothing on Preview", async () => {
    const stub = installCopyStub()
    const user = userEvent.setup()
    renderForm()
    expect(screen.queryByRole("button", { name: "Apply changes" })).toBeNull()
    expect(screen.getByRole("button", { name: "Preview changes" })).toBeEnabled()
    expect(screen.getByRole("button", { name: "Changed values" })).toHaveAttribute("aria-pressed", "true")
    expect(screen.getByText("Copies only the values the other project changed from the system defaults")).toBeInTheDocument()
    const shown = await preview(user)
    expect(within(shown).getByText("Max attempts")).toBeInTheDocument()
    expect(within(shown).getByText("Changes")).toBeInTheDocument()
    expect(within(shown).getByText("Not copied")).toBeInTheDocument()
    expect(within(shown).getByText(/The target system allows metadata only\./)).toBeInTheDocument()
    expect(within(shown).getByRole("checkbox", { name: /^private/ })).toBeDisabled()
    expect(within(shown).getByText("The credential is not granted to this project.")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Apply changes" })).toBeEnabled()
    expect(screen.queryByRole("button", { name: "Preview changes" })).toBeNull()
    expect(stub.requests.filter((req) => req.url === APPLY_URL)).toHaveLength(0)
    expect(stub.requests.find((req) => req.url === PREVIEW_URL)?.body).toEqual({
      source_project_id: SOURCE,
      expected_source_revision: 7,
      expected_target_revision: 4,
      expected_system_revision: 2,
      mode: "overrides_only",
      binding_versions: {},
    })
  })

  it("keeps Preview enabled and asks for a source inline when none is chosen", async () => {
    const stub = installCopyStub()
    const user = userEvent.setup()
    renderForm()
    await user.click(screen.getByRole("button", { name: "Preview changes" }))
    expect(screen.getByText("Choose a project to copy from")).toBeInTheDocument()
    expect(screen.getByLabelText("Source project")).toHaveAttribute("aria-invalid", "true")
    expect(stub.requests.filter((req) => req.url === PREVIEW_URL)).toHaveLength(0)
    await chooseSource(user)
    expect(screen.queryByText("Choose a project to copy from")).toBeNull()
  })

  it("invalidates the preview on a mode change but keeps it on a binding change", async () => {
    installCopyStub()
    const user = userEvent.setup()
    renderForm()
    await preview(user)
    await user.click(screen.getByRole("checkbox", { name: "primary" }))
    expect(screen.getByTestId("copy-preview")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Apply changes" })).toBeEnabled()
    await user.click(screen.getByRole("button", { name: "All current values" }))
    expect(screen.queryByTestId("copy-preview")).toBeNull()
    expect(screen.queryByRole("button", { name: "Apply changes" })).toBeNull()
    expect(screen.getByText("Copies every current value; this project stops following the system defaults")).toBeInTheDocument()
  })

  it("applies with the preview revisions and the selected binding versions", async () => {
    const stub = installCopyStub()
    const user = userEvent.setup()
    const { onApplied, onClose } = renderForm()
    await preview(user)
    await user.click(screen.getByRole("checkbox", { name: "primary" }))
    expect(screen.getByRole("checkbox", { name: "primary" })).toBeChecked()
    await user.click(screen.getByRole("button", { name: "Apply changes" }))
    await waitFor(() => expect(onApplied).toHaveBeenCalled())
    expect(stub.requests.filter((req) => req.url === PREVIEW_URL)).toHaveLength(1)
    expect(stub.requests.find((req) => req.url === APPLY_URL)?.body).toEqual({
      source_project_id: SOURCE,
      expected_source_revision: 7,
      expected_target_revision: 4,
      expected_system_revision: 2,
      mode: "overrides_only",
      binding_versions: { b1: 3 },
    })
    expect(onApplied.mock.calls[0]?.[1]).toBe("Copied 1 setting.")
    expect(onClose).toHaveBeenCalled()
  })

  it("asks for a new preview on a 409", async () => {
    installCopyStub(() => err(409, { detail: { code: "SETTINGS_REVISION_CONFLICT", message: "stale" } }))
    const user = userEvent.setup()
    const { onApplied } = renderForm()
    await preview(user)
    await user.click(screen.getByRole("button", { name: "Apply changes" }))
    expect(await screen.findByText("Settings changed since the preview. Preview again")).toBeInTheDocument()
    expect(screen.queryByTestId("copy-preview")).toBeNull()
    expect(screen.getByRole("button", { name: "Preview changes" })).toBeEnabled()
    expect(onApplied).not.toHaveBeenCalled()
  })
})
