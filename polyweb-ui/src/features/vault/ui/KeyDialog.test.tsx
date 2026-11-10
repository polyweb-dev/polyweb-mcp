import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { KEYLESS_AUTH_LABEL } from "@/domains/providers"
import { KeyDialog } from "./KeyDialog"

const api = vi.hoisted(() => ({ createVaultKey: vi.fn() }))
vi.mock("@/domains/vault", async (original) => ({ ...await original<typeof import("@/domains/vault")>(), ...api }))

beforeEach(() => vi.resetAllMocks())

describe("KeyDialog", () => {
  it("marks both empty required fields and does not name a hidden limit", async () => {
    render(<KeyDialog mode="add" onClose={vi.fn()} onSaved={vi.fn()} />)
    expect(screen.getByLabelText("Label")).toHaveValue("Brave Search key")
    await userEvent.clear(screen.getByLabelText("Label"))
    await userEvent.click(screen.getByRole("button", { name: "Add key" }))
    expect(screen.getByLabelText("Label")).toHaveAttribute("aria-invalid", "true")
    expect(screen.getByLabelText("Label")).toHaveAccessibleDescription("Enter a label")
    expect(screen.getByLabelText("API key")).toHaveAttribute("aria-invalid", "true")
    expect(screen.getByLabelText("API key")).toHaveAccessibleDescription("Enter the API key")
    expect(screen.getAllByRole("alert")).toHaveLength(2)
    expect(screen.queryByText(/key limit/i)).not.toBeInTheDocument()
    expect(api.createVaultKey).not.toHaveBeenCalled()
  })

  it("preserves a typed secret while the user corrects the label", async () => {
    render(<KeyDialog mode="add" onClose={vi.fn()} onSaved={vi.fn()} />)
    await userEvent.clear(screen.getByLabelText("Label"))
    await userEvent.type(screen.getByLabelText("API key"), "secret")
    await userEvent.click(screen.getByRole("button", { name: "Add key" }))
    expect(screen.getByLabelText("API key")).toHaveValue("secret")
    await userEvent.type(screen.getByLabelText("Label"), "Main")
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Add key" }))
    await waitFor(() => expect(api.createVaultKey).toHaveBeenCalledWith(expect.objectContaining({ secret: "secret", capacity: null })))
  })

  it("accepts an empty optional limit when Advanced is open", async () => {
    render(<KeyDialog mode="add" onClose={vi.fn()} onSaved={vi.fn()} />)
    await userEvent.click(screen.getByRole("button", { name: "Advanced" }))
    await userEvent.type(screen.getByLabelText("Label"), "Main")
    await userEvent.type(screen.getByLabelText("API key"), "secret")
    await userEvent.click(screen.getByRole("button", { name: "Add key" }))
    await waitFor(() => expect(api.createVaultKey).toHaveBeenCalledWith(expect.objectContaining({ capacity: null })))
  })

  it("marks an invalid visible limit, then ignores it when Advanced closes", async () => {
    render(<KeyDialog mode="add" onClose={vi.fn()} onSaved={vi.fn()} />)
    await userEvent.click(screen.getByRole("button", { name: "Advanced" }))
    await userEvent.type(screen.getByLabelText("Key limit"), "0")
    await userEvent.type(screen.getByLabelText("Label"), "Main")
    await userEvent.type(screen.getByLabelText("API key"), "secret")
    await userEvent.click(screen.getByRole("button", { name: "Add key" }))
    expect(screen.getByLabelText("Key limit")).toHaveAccessibleDescription("Enter a positive whole number")
    expect(api.createVaultKey).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole("button", { name: "Advanced" }))
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Add key" }))
    await waitFor(() => expect(api.createVaultKey).toHaveBeenCalledWith(expect.objectContaining({ capacity: null })))
  })

  describe("KeyDialog keyless creation (TASK-000065 AC#2)", () => {
    it("saves a Keenable key without an API key secret", async () => {
      const user = userEvent.setup()
      const onSaved = vi.fn()
      render(<KeyDialog mode="add" onClose={vi.fn()} onSaved={onSaved} />)
      await user.click(screen.getByRole("combobox", { name: "Provider" }))
      await user.click(await screen.findByRole("option", { name: "Keenable" }))
      // The catalog always offers an Authentication combobox for Keenable;
      // choose its keyless mode and expect a secret-free save.
      await user.click(screen.getByRole("combobox", { name: "Authentication" }))
      await user.click(await screen.findByRole("option", { name: KEYLESS_AUTH_LABEL }))
      expect(screen.queryByLabelText("API key")).not.toBeInTheDocument()
      await user.clear(screen.getByLabelText("Label"))
      await user.type(screen.getByLabelText("Label"), "Keenable keyless")
      await user.click(screen.getByRole("button", { name: "Add key" }))
      await waitFor(() => expect(api.createVaultKey).toHaveBeenCalledWith(expect.objectContaining({
        provider_type: "keenable", label: "Keenable keyless", auth_mode: "keyless",
      })))
      await waitFor(() => expect(onSaved).toHaveBeenCalled())
      expect(api.createVaultKey).toHaveBeenCalledTimes(1)
      expect(api.createVaultKey.mock.calls[0]?.[0]).not.toHaveProperty("secret")
    })
  })
})
