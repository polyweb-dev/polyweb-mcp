import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { requestJson } from "@/shared/api/client"
import { KeyBalances } from "./KeyBalances"
import { KeyBalancesRefreshScope } from "../model/keyBalanceContext"

vi.mock("@/shared/api/client", () => ({ requestJson: vi.fn() }))

const key = (id: string, owner = "owner@example.com") => ({
  key_id: id,
  label: `Key ${id}`,
  owner_email: owner,
  auth_mode: "api_key",
  oauth_connected: null,
  balance: { remaining: "12.50", native_unit: "usd", observed_at: "2026-01-01T12:00:00Z" },
})
const refreshDashboard = vi.fn().mockResolvedValue(undefined)

function show(isAdmin = true, email: string | null = null) {
  return render(<KeyBalances providerId="parallel" providerName="Parallel" accountId="account" isAdmin={isAdmin} email={email} refreshDashboard={refreshDashboard} />)
}

beforeEach(() => {
  vi.resetAllMocks()
  refreshDashboard.mockResolvedValue(undefined)
})
afterEach(cleanup)

describe("KeyBalances", () => {
  it("shows loading and empty states", async () => {
    vi.mocked(requestJson).mockResolvedValue([])
    show()
    expect(screen.getByRole("status")).toHaveTextContent("Loading key balances")
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull())
    expect(screen.queryByText("No key balances")).toBeNull()
  })

  it("shows an error and retries", async () => {
    vi.mocked(requestJson).mockRejectedValueOnce(new Error("failure")).mockResolvedValueOnce([])
    show()
    expect(await screen.findByRole("alert")).toHaveTextContent("Key balances unavailable")
    await userEvent.click(screen.getByRole("button", { name: "Retry" }))
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull())
    expect(screen.queryByText("No key balances")).toBeNull()
  })

  it("shows key labels, owners, balances and refresh times", async () => {
    vi.mocked(requestJson).mockResolvedValue([key("1"), { ...key("2"), balance: null }])
    show()
    expect(await screen.findByText("Key 1")).toBeInTheDocument()
    expect(screen.queryByText("owner@example.com")).toBeNull()
    expect(screen.getByText(/\$12.50 left/)).toBeInTheDocument()
    expect(screen.getAllByText("—")[0]).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Refresh Parallel balances" })).toBeInTheDocument()
  })

  it("collapses more than three keys to a count", async () => {
    vi.mocked(requestJson).mockResolvedValue([key("1"), key("2"), key("3"), key("4")])
    show()
    const button = await screen.findByRole("button", { name: "Show 4 keys" })
    expect(button).toHaveAttribute("aria-expanded", "false")
    expect(screen.queryByText("Key 1")).toBeNull()
    await userEvent.click(button)
    expect(screen.getByText("Key 4")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Hide 4 keys" })).toHaveAttribute("aria-expanded", "true")
  })

  it("shows refresh only for an owner or administrator", async () => {
    vi.mocked(requestJson).mockResolvedValueOnce([key("1"), key("2", "other@example.com")])
      .mockResolvedValueOnce({ status: "synced" }).mockResolvedValueOnce([key("1"), key("2", "other@example.com")])
    show(false, "owner@example.com")
    await userEvent.click(await screen.findByRole("button", { name: "Refresh Parallel balances" }))
    await waitFor(() => expect(refreshDashboard).toHaveBeenCalledOnce())
    expect(requestJson).toHaveBeenCalledWith("/api/v1/providers/parallel/limits/keys/1/sync", { method: "POST" })
    expect(requestJson).not.toHaveBeenCalledWith("/api/v1/providers/parallel/limits/keys/2/sync", { method: "POST" })
  })

  it("refreshes one key and reloads its balances", async () => {
    vi.mocked(requestJson).mockResolvedValueOnce([key("1")]).mockResolvedValueOnce({ status: "synced" }).mockResolvedValueOnce([key("1")])
    show()
    await userEvent.click(await screen.findByRole("button", { name: "Refresh Parallel balances" }))
    await waitFor(() => expect(refreshDashboard).toHaveBeenCalledOnce())
    expect(requestJson).toHaveBeenCalledWith("/api/v1/providers/parallel/limits/keys/1/sync", { method: "POST" })
    expect(await screen.findByText("Updated")).toBeInTheDocument()
  })

  it("refreshes all eligible keys with one control", async () => {
    vi.mocked(requestJson).mockResolvedValueOnce([key("1"), key("2")])
      .mockResolvedValueOnce({ status: "synced" }).mockResolvedValueOnce({ status: "synced" })
      .mockResolvedValueOnce([key("1"), key("2")])
    show()
    await userEvent.click(await screen.findByRole("button", { name: "Refresh Parallel balances" }))
    await waitFor(() => expect(refreshDashboard).toHaveBeenCalledOnce())
    expect(requestJson).toHaveBeenCalledWith("/api/v1/providers/parallel/limits/keys/1/sync", { method: "POST" })
    expect(requestJson).toHaveBeenCalledWith("/api/v1/providers/parallel/limits/keys/2/sync", { method: "POST" })
  })

  it("does not offer refresh when usage is not reported", async () => {
    vi.mocked(requestJson).mockResolvedValue([key("1")])
    render(<KeyBalancesRefreshScope.Provider value={false}>
      <KeyBalances providerId="parallel" providerName="Parallel" accountId="account" isAdmin email={null} refreshDashboard={refreshDashboard} />
    </KeyBalancesRefreshScope.Provider>)
    expect(await screen.findByText("Key 1")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Refresh Parallel balances" })).toBeNull()
  })

  it("shows a refresh failure without exposing the response", async () => {
    vi.mocked(requestJson).mockResolvedValueOnce([key("1")]).mockRejectedValueOnce(new Error("secret")).mockResolvedValueOnce([key("1")])
    show()
    await userEvent.click(await screen.findByRole("button", { name: "Refresh Parallel balances" }))
    expect(await screen.findByText("Refresh failed")).toBeInTheDocument()
    expect(screen.queryByText("secret")).toBeNull()
  })

  it("shows a skipped refresh without claiming an update", async () => {
    vi.mocked(requestJson).mockResolvedValueOnce([key("1")])
      .mockResolvedValueOnce({ status: "skipped", reason: "cadence" })
      .mockResolvedValueOnce([key("1")])
    show()
    await userEvent.click(await screen.findByRole("button", { name: "Refresh Parallel balances" }))
    expect(await screen.findByText("Refreshed recently, try again in a minute")).toBeInTheDocument()
    expect(screen.queryByText("Updated")).toBeNull()
  })
})
