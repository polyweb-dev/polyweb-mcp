import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { apiKeyFixture } from "@/test/accessFixtures"
import type { ProjectApiKeysController } from "../model/useProjectApiKeysController"
import { RotateApiKeyForm } from "./RotateApiKeyForm"

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

function renderForm(controller: ProjectApiKeysController) {
  const key = controller.rotatingKey ?? apiKeyFixture({ label: "CI runner" })
  render(<RotateApiKeyForm apiKey={key} controller={controller} />)
  return key
}

describe("RotateApiKeyForm", () => {
  it("offers the four overlaps with 24 hours by default and keeps the current lifetime", async () => {
    renderForm(controllerStub())
    const overlap = screen.getByRole("combobox", { name: "Old key stays valid for" })
    expect(overlap).toHaveTextContent("24 hours")
    await userEvent.setup().click(overlap)
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual([
      "Revoke old key now",
      "1 hour",
      "24 hours",
      "7 days",
    ])
    expect(screen.getByRole("button", { name: "Keep current" })).toHaveAttribute("aria-pressed", "true")
    expect(screen.getByText("The new key keeps the old key's expiry date")).toBeInTheDocument()
  })

  it("rotates with the chosen overlap and expiry", async () => {
    const controller = controllerStub()
    const user = userEvent.setup()
    const key = renderForm(controller)

    await user.click(screen.getByRole("combobox", { name: "Old key stays valid for" }))
    await user.click(screen.getByRole("option", { name: "7 days" }))
    await user.click(screen.getByRole("button", { name: "No expiration" }))
    await user.click(screen.getByRole("button", { name: "Rotate key" }))
    expect(controller.rotate).toHaveBeenCalledWith(key, { overlapSeconds: 604_800, expiry: { kind: "never" } })
  })

  it("rotates with the default overlap and omitted expiry", async () => {
    const controller = controllerStub()
    const key = renderForm(controller)
    await userEvent.setup().click(screen.getByRole("button", { name: "Rotate key" }))
    expect(controller.rotate).toHaveBeenCalledWith(key, { overlapSeconds: 86_400, expiry: { kind: "default" } })
  })

  it("cancels without rotating", async () => {
    const controller = controllerStub()
    renderForm(controller)
    await userEvent.setup().click(screen.getByRole("button", { name: "Cancel" }))
    expect(controller.openRotate).toHaveBeenCalledWith(null)
    expect(controller.rotate).not.toHaveBeenCalled()
  })

  it("shows the controller message and rejects a past custom date under the date field", async () => {
    const controller = controllerStub({ message: "This key is no longer active." })
    const user = userEvent.setup()
    renderForm(controller)
    expect(screen.getByRole("alert")).toHaveTextContent("This key is no longer active.")

    await user.click(screen.getByRole("button", { name: "Custom date" }))
    await user.type(screen.getByLabelText("Expiration date"), "2000-01-01")
    await user.click(screen.getByRole("button", { name: "Rotate key" }))
    expect(screen.getByText("Choose an expiration date in the future")).toBeInTheDocument()
    expect(screen.getByLabelText("Expiration date")).toHaveAttribute("aria-invalid", "true")
    expect(controller.showMessage).not.toHaveBeenCalled()
    expect(controller.rotate).not.toHaveBeenCalled()
  })

  it("puts Cancel first and the primary Rotate key last", () => {
    renderForm(controllerStub())
    const cancel = screen.getByRole("button", { name: "Cancel" })
    const rotate = screen.getByRole("button", { name: "Rotate key" })
    expect(cancel.compareDocumentPosition(rotate) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })
})
