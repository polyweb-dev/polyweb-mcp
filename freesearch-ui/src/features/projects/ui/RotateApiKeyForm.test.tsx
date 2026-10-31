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
  it("offers the four overlaps with 24 hours by default and keeps the current lifetime", () => {
    renderForm(controllerStub())
    const overlap = screen.getByLabelText("Old key stays valid for")
    expect(Array.from((overlap as HTMLSelectElement).options).map((option) => option.textContent)).toEqual([
      "Revoke old key now",
      "1 hour",
      "24 hours",
      "7 days",
    ])
    expect(overlap).toHaveValue("86400")
    expect(screen.getByRole("radio", { name: "Keep current lifetime" })).toBeChecked()
  })

  it("rotates with the chosen overlap and expiry", async () => {
    const controller = controllerStub()
    const user = userEvent.setup()
    const key = renderForm(controller)

    await user.selectOptions(screen.getByLabelText("Old key stays valid for"), "7 days")
    await user.click(screen.getByRole("radio", { name: "No expiration" }))
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

  it("rejects a past custom date and shows the controller message", async () => {
    const controller = controllerStub({ message: "This key is no longer active." })
    const user = userEvent.setup()
    renderForm(controller)
    expect(screen.getByRole("alert")).toHaveTextContent("This key is no longer active.")

    await user.click(screen.getByRole("radio", { name: "Custom date" }))
    await user.type(screen.getByLabelText("Expiration date"), "2000-01-01")
    await user.click(screen.getByRole("button", { name: "Rotate key" }))
    expect(controller.showMessage).toHaveBeenCalledWith("Choose an expiration date in the future.")
    expect(controller.rotate).not.toHaveBeenCalled()
  })
})
