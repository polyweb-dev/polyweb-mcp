import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { ProjectApiKeysController } from "../model/useProjectApiKeysController"
import { IssueApiKeyForm } from "./IssueApiKeyForm"

function controllerStub(overrides: Partial<ProjectApiKeysController> = {}): ProjectApiKeysController {
  return {
    keys: { status: "ready", data: [], reload: vi.fn(async () => []) },
    emailsByUserId: null,
    pending: false,
    message: null,
    showMessage: vi.fn(),
    revealedKey: null,
    dismissReveal: vi.fn(),
    issue: vi.fn(async () => true),
    rotate: vi.fn(async () => true),
    revoke: vi.fn(async () => {}),
    confirmingRevokeId: null,
    requestRevoke: vi.fn(),
    rotatingKey: null,
    openRotate: vi.fn(),
    ...overrides,
  }
}

describe("IssueApiKeyForm", () => {
  it("is a region named by its heading with both permitted scopes checked", () => {
    render(<IssueApiKeyForm controller={controllerStub()} permittedScopes={["search.execute", "fetch.execute"]} />)
    expect(screen.getByRole("region", { name: "New API key" })).toBeInTheDocument()
    expect(screen.getByRole("checkbox", { name: "Search" })).toBeChecked()
    expect(screen.getByRole("checkbox", { name: "Fetch" })).toBeChecked()
  })

  it("issues the trimmed label, the ordered scopes and the default expiry, then resets", async () => {
    const controller = controllerStub()
    const user = userEvent.setup()
    render(<IssueApiKeyForm controller={controller} permittedScopes={["search.execute", "fetch.execute"]} />)

    await user.click(screen.getByRole("checkbox", { name: "Search" }))
    await user.click(screen.getByRole("checkbox", { name: "Search" }))
    await user.type(screen.getByLabelText("Label"), "  CI  ")
    await user.click(screen.getByRole("button", { name: "Issue key" }))

    expect(controller.issue).toHaveBeenCalledWith({
      label: "CI",
      scopes: ["search.execute", "fetch.execute"],
      expiry: { kind: "default" },
    })
    expect(screen.getByLabelText("Label")).toHaveValue("")
  })

  it("re-checks every permitted scope after a successful issue", async () => {
    const controller = controllerStub()
    const user = userEvent.setup()
    render(<IssueApiKeyForm controller={controller} permittedScopes={["search.execute", "fetch.execute"]} />)

    await user.click(screen.getByRole("checkbox", { name: "Fetch" }))
    await user.type(screen.getByLabelText("Label"), "Search only")
    await user.click(screen.getByRole("button", { name: "Custom date" }))
    await user.type(screen.getByLabelText("Expiration date"), "2099-06-30")
    await user.click(screen.getByRole("button", { name: "Issue key" }))

    expect(controller.issue).toHaveBeenCalledWith(expect.objectContaining({ scopes: ["search.execute"] }))
    expect(screen.getByRole("checkbox", { name: "Search" })).toBeChecked()
    expect(screen.getByRole("checkbox", { name: "Fetch" })).toBeChecked()
    expect(screen.getByRole("button", { name: "90 days" })).toHaveAttribute("aria-pressed", "true")
    expect(screen.queryByLabelText("Expiration date")).toBeNull()
  })

  it("keeps an unchecked scope when the issue fails", async () => {
    const controller = controllerStub({ issue: vi.fn(async () => false) })
    const user = userEvent.setup()
    render(<IssueApiKeyForm controller={controller} permittedScopes={["search.execute", "fetch.execute"]} />)
    await user.click(screen.getByRole("checkbox", { name: "Fetch" }))
    await user.type(screen.getByLabelText("Label"), "x")
    await user.click(screen.getByRole("button", { name: "Issue key" }))
    expect(screen.getByRole("checkbox", { name: "Fetch" })).not.toBeChecked()
  })

  it("keeps the draft when the issue fails", async () => {
    const controller = controllerStub({ issue: vi.fn(async () => false) })
    const user = userEvent.setup()
    render(<IssueApiKeyForm controller={controller} permittedScopes={["search.execute"]} />)
    await user.type(screen.getByLabelText("Label"), "Keep me")
    await user.click(screen.getByRole("button", { name: "No expiration" }))
    await user.click(screen.getByRole("button", { name: "Issue key" }))
    expect(controller.issue).toHaveBeenCalledWith({ label: "Keep me", scopes: ["search.execute"], expiry: { kind: "never" } })
    expect(screen.getByLabelText("Label")).toHaveValue("Keep me")
    expect(screen.getByRole("button", { name: "No expiration" })).toHaveAttribute("aria-pressed", "true")
  })

  it("disables a scope the caller lacks", () => {
    render(<IssueApiKeyForm controller={controllerStub()} permittedScopes={["fetch.execute"]} />)
    expect(screen.getByRole("checkbox", { name: "Search" })).toBeDisabled()
    expect(screen.getByRole("checkbox", { name: "Search" })).not.toBeChecked()
    expect(screen.getByRole("checkbox", { name: "Fetch" })).toBeChecked()
  })

  it("shows validation errors under their fields without issuing", async () => {
    const controller = controllerStub()
    const user = userEvent.setup()
    render(<IssueApiKeyForm controller={controller} permittedScopes={[]} />)
    await user.click(screen.getByRole("button", { name: "Issue key" }))
    expect(screen.getByLabelText("Label")).toHaveAttribute("aria-invalid", "true")
    expect(screen.getByText("Enter a label for the key")).toBeInTheDocument()
    expect(screen.getByText("Choose at least one scope")).toBeInTheDocument()
    await user.type(screen.getByLabelText("Label"), "x")
    await user.click(screen.getByRole("button", { name: "Issue key" }))
    expect(screen.queryByText("Enter a label for the key")).toBeNull()
    expect(screen.getByRole("alert")).toHaveTextContent("Choose at least one scope")
    expect(controller.showMessage).not.toHaveBeenCalled()
    expect(controller.issue).not.toHaveBeenCalled()
  })

  it("rejects a past custom date under the date field", async () => {
    const controller = controllerStub()
    const user = userEvent.setup()
    render(<IssueApiKeyForm controller={controller} permittedScopes={["search.execute"]} />)
    await user.type(screen.getByLabelText("Label"), "Dated")
    await user.click(screen.getByRole("button", { name: "Custom date" }))
    await user.type(screen.getByLabelText("Expiration date"), "2000-01-01")
    await user.click(screen.getByRole("button", { name: "Issue key" }))
    expect(screen.getByLabelText("Expiration date")).toHaveAttribute("aria-invalid", "true")
    expect(screen.getByRole("alert")).toHaveTextContent("Choose an expiration date in the future")
    expect(controller.issue).not.toHaveBeenCalled()
  })

  it("keeps no draft in storage", async () => {
    window.localStorage.clear()
    window.sessionStorage.clear()
    const user = userEvent.setup()
    render(<IssueApiKeyForm controller={controllerStub()} permittedScopes={["search.execute"]} />)
    await user.type(screen.getByLabelText("Label"), "Unsaved")
    expect(window.localStorage.length).toBe(0)
    expect(window.sessionStorage.length).toBe(0)
  })
})
