import { describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
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

/** The one row menu trigger: a `…` button named after the key label. */
function actionsTrigger(label: string): HTMLElement {
  return screen.getByRole("button", { name: `Actions for ${label}` })
}

describe("ApiKeyRowActions", () => {
  it("offers Rotate and Revoke named by the key label for an active key", async () => {
    const controller = controllerStub()
    const key = apiKeyFixture({ id: "k1", label: "CI runner" })
    render(<ApiKeyRowActions apiKey={key} canRotate controller={controller} />)
    const user = userEvent.setup()

    const trigger = actionsTrigger("CI runner")
    expect(trigger).toHaveAttribute("aria-label", "Actions for CI runner")

    await user.click(trigger)
    await user.click(screen.getByRole("button", { name: "Rotate key" }))
    expect(controller.openRotate).toHaveBeenCalledWith(key)

    await user.click(actionsTrigger("CI runner"))
    await user.click(screen.getByRole("button", { name: "Revoke key" }))
    expect(controller.requestRevoke).toHaveBeenCalledWith("k1")
    expect(controller.revoke).not.toHaveBeenCalled()
  })

  it("hides Rotate when rotation is not allowed", async () => {
    const user = userEvent.setup()
    render(
      <ApiKeyRowActions
        apiKey={apiKeyFixture({ label: "CI runner" })}
        canRotate={false}
        controller={controllerStub()}
      />
    )
    await user.click(actionsTrigger("CI runner"))
    expect(screen.queryByRole("button", { name: "Rotate key" })).toBeNull()
    expect(screen.getByRole("button", { name: "Revoke key" })).toBeInTheDocument()
  })

  it("asks for confirmation in the shared dialog before revoking", async () => {
    const key = apiKeyFixture({ id: "k1", label: "CI runner" })
    const controller = controllerStub({ confirmingRevokeId: "k1" })
    render(<ApiKeyRowActions apiKey={key} canRotate controller={controller} />)
    const user = userEvent.setup()

    const dialog = screen.getByRole("dialog", { name: "Revoke CI runner" })
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }))
    expect(controller.requestRevoke).toHaveBeenCalledWith(null)
    await user.click(within(dialog).getByRole("button", { name: "Revoke key" }))
    expect(controller.revoke).toHaveBeenCalledWith(key)
  })

  it("shows no confirmation for another key", () => {
    const controller = controllerStub({ confirmingRevokeId: "other" })
    render(<ApiKeyRowActions apiKey={apiKeyFixture({ id: "k1", label: "CI runner" })} canRotate controller={controller} />)
    expect(screen.queryByRole("dialog")).toBeNull()
    expect(screen.getByRole("button", { name: "Actions for CI runner" })).toBeInTheDocument()
  })

  it.each([["revoked" as const], ["expired" as const]])("renders no controls for a %s key", (status) => {
    const { container } = render(
      <ApiKeyRowActions apiKey={apiKeyFixture({ status })} canRotate controller={controllerStub()} />
    )
    expect(container).toBeEmptyDOMElement()
  })

  it("disables the controls while a mutation is pending", async () => {
    const user = userEvent.setup()
    render(
      <ApiKeyRowActions
        apiKey={apiKeyFixture({ label: "CI runner" })}
        canRotate
        controller={controllerStub({ pending: true })}
      />
    )
    const trigger = actionsTrigger("CI runner")
    expect(trigger).toBeDisabled()
    // A disabled trigger opens no menu, so no row action is reachable.
    await user.click(trigger)
    expect(screen.queryByRole("button", { name: "Rotate key" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Revoke key" })).toBeNull()
    expect(trigger).toBeDisabled()
  })
})
