import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { apiKeyFixture } from "@/test/accessFixtures"
import type { ProjectApiKeysController } from "../model/useProjectApiKeysController"
import { ApiKeyRowActions } from "./ApiKeyRowActions"

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

describe("ApiKeyRowActions", () => {
  it("offers Rotate and Revoke named by the key label for an active key", async () => {
    const controller = controllerStub()
    const key = apiKeyFixture({ id: "k1", label: "CI runner" })
    render(<ApiKeyRowActions apiKey={key} canRotate controller={controller} />)
    const user = userEvent.setup()

    await user.click(screen.getByRole("button", { name: "Rotate CI runner" }))
    expect(controller.openRotate).toHaveBeenCalledWith(key)
    await user.click(screen.getByRole("button", { name: "Revoke CI runner" }))
    expect(controller.requestRevoke).toHaveBeenCalledWith("k1")
    expect(controller.revoke).not.toHaveBeenCalled()
  })

  it("hides Rotate when rotation is not allowed", () => {
    render(<ApiKeyRowActions apiKey={apiKeyFixture({ label: "CI runner" })} canRotate={false} controller={controllerStub()} />)
    expect(screen.queryByRole("button", { name: "Rotate CI runner" })).toBeNull()
    expect(screen.getByRole("button", { name: "Revoke CI runner" })).toBeInTheDocument()
  })

  it("asks for an inline confirmation before revoking", async () => {
    const key = apiKeyFixture({ id: "k1", label: "CI runner" })
    const controller = controllerStub({ confirmingRevokeId: "k1" })
    render(<ApiKeyRowActions apiKey={key} canRotate controller={controller} />)
    const user = userEvent.setup()

    await user.click(screen.getByRole("button", { name: "Cancel" }))
    expect(controller.requestRevoke).toHaveBeenCalledWith(null)
    await user.click(screen.getByRole("button", { name: "Confirm revoke" }))
    expect(controller.revoke).toHaveBeenCalledWith(key)
  })

  it.each([["revoked" as const], ["expired" as const]])("renders no controls for a %s key", (status) => {
    const { container } = render(
      <ApiKeyRowActions apiKey={apiKeyFixture({ status })} canRotate controller={controllerStub()} />
    )
    expect(container).toBeEmptyDOMElement()
  })

  it("disables the controls while a mutation is pending", () => {
    render(<ApiKeyRowActions apiKey={apiKeyFixture({ label: "CI runner" })} canRotate controller={controllerStub({ pending: true })} />)
    expect(screen.getByRole("button", { name: "Revoke CI runner" })).toBeDisabled()
    expect(screen.getByRole("button", { name: "Rotate CI runner" })).toBeDisabled()
  })
})
