import { describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { apiKeyFixture } from "@/test/accessFixtures"
import type { ProjectApiKeysController } from "../model/useProjectApiKeysController"
import { RotateApiKeyDialog } from "./RotateApiKeyDialog"

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

describe("RotateApiKeyDialog", () => {
  it("renders nothing until a key is chosen", () => {
    render(<RotateApiKeyDialog controller={controllerStub()} />)
    expect(screen.queryByRole("dialog")).toBeNull()
  })

  it("is named after the key and holds the rotate form", () => {
    render(<RotateApiKeyDialog controller={controllerStub({ rotatingKey: apiKeyFixture({ label: "CI runner" }) })} />)
    const dialog = screen.getByRole("dialog", { name: "Rotate CI runner" })
    expect(within(dialog).getByLabelText("Old key stays valid for")).toBeInTheDocument()
    expect(within(dialog).getByRole("button", { name: "Rotate key" })).toBeInTheDocument()
  })

  it("closes through the controller on Escape", async () => {
    const controller = controllerStub({ rotatingKey: apiKeyFixture({ label: "CI runner" }) })
    render(<RotateApiKeyDialog controller={controller} />)
    await userEvent.setup().keyboard("{Escape}")
    expect(controller.openRotate).toHaveBeenCalledWith(null)
  })
})
