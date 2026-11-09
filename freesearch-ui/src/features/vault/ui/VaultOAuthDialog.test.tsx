import { act, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { VaultOAuthDialog } from "./VaultOAuthDialog"

const api = vi.hoisted(() => ({ startVaultOAuth: vi.fn(), pollVaultOAuth: vi.fn() }))
vi.mock("@/domains/vault", () => api)
const device = { user_code: "ABCD-EFGH", verification_uri: "https://parallel.ai/verify", interval: 1, expires_in: 60 }

beforeEach(() => {
  vi.resetAllMocks()
  api.startVaultOAuth.mockResolvedValue(device)
  api.pollVaultOAuth.mockResolvedValue({ status: "pending" })
})
afterEach(() => vi.useRealTimers())

describe("VaultOAuthDialog", () => {
  it("shows numbered steps, copies the code, and has one wait status and Cancel", async () => {
    const user = userEvent.setup()
    render(<VaultOAuthDialog keyId="k1" onClose={vi.fn()} onConnected={vi.fn()} />)
    expect(await screen.findByText(device.user_code)).toBeInTheDocument()
    const steps = screen.getAllByRole("listitem")
    expect(steps).toHaveLength(2)
    expect(steps[0]).toHaveTextContent("Copy this code")
    expect(within(steps[1]!).getByRole("link", { name: "Open the Parallel verification page" })).toHaveAttribute("href", device.verification_uri)
    await user.click(screen.getByRole("button", { name: "Copy" }))
    expect(await navigator.clipboard.readText()).toBe(device.user_code)
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument()
    expect(screen.getAllByRole("status")).toHaveLength(1)
    expect(screen.getByRole("status")).toHaveTextContent("Waiting for approval")
    expect(screen.getByRole("status").querySelector("svg")).toHaveClass("animate-spin")
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Close", exact: true })).toHaveAttribute("data-slot", "dialog-close")
  })

  it("shows copy failure without a false success label", async () => {
    const user = userEvent.setup()
    vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(new Error("denied"))
    render(<VaultOAuthDialog keyId="k1" onClose={vi.fn()} onConnected={vi.fn()} />)
    await user.click(await screen.findByRole("button", { name: "Copy" }))
    expect(screen.getByRole("alert")).toHaveTextContent("Cannot copy the code. Select and copy it")
    expect(screen.queryByRole("button", { name: "Copied" })).not.toBeInTheDocument()
  })

  it("cancels without further polling and aborts the current request", async () => {
    const close = vi.fn()
    const view = render(<VaultOAuthDialog keyId="k1" onClose={close} onConnected={vi.fn()} />)
    await screen.findByText(device.user_code)
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }))
    expect(close).toHaveBeenCalledOnce()
    const signal = api.startVaultOAuth.mock.calls[0]?.[1] as AbortSignal
    view.unmount()
    expect(signal.aborted).toBe(true)
    expect(api.pollVaultOAuth).not.toHaveBeenCalled()
  })

  it("uses the polling interval and stops after approval", async () => {
    vi.useFakeTimers()
    api.pollVaultOAuth.mockResolvedValueOnce({ status: "pending", interval: 2 }).mockResolvedValueOnce({ status: "connected" })
    const connected = vi.fn()
    render(<VaultOAuthDialog keyId="k1" onClose={vi.fn()} onConnected={connected} />)
    await act(async () => { await Promise.resolve() })
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(api.pollVaultOAuth).toHaveBeenCalledTimes(1)
    await act(async () => { await vi.advanceTimersByTimeAsync(1999) })
    expect(api.pollVaultOAuth).toHaveBeenCalledTimes(1)
    await act(async () => { await vi.advanceTimersByTimeAsync(1) })
    expect(connected).toHaveBeenCalledOnce()
    expect(screen.getByRole("status")).toHaveTextContent("Connected")
    expect(screen.getByRole("status").querySelector("svg")).toBeNull()
    await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
    expect(api.pollVaultOAuth).toHaveBeenCalledTimes(2)
  })

  it("reports a start failure", async () => {
    api.startVaultOAuth.mockRejectedValue(new Error("failed"))
    render(<VaultOAuthDialog keyId="k1" onClose={vi.fn()} onConnected={vi.fn()} />)
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Cannot connect to Parallel"))
    expect(screen.queryByRole("list")).not.toBeInTheDocument()
  })
})
