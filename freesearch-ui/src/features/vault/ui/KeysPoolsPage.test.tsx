import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { ApiError } from "@/shared/api/http"
import { NotificationsContext } from "@/shared/notifications/context"
import { KeysPoolsPage } from "./KeysPoolsPage"

const api = vi.hoisted(() => ({
  listVaultKeys: vi.fn(), listVaultProjects: vi.fn(), listKeyPools: vi.fn(),
  createVaultKey: vi.fn(), updateVaultKey: vi.fn(), rotateVaultKey: vi.fn(),
  deleteVaultKey: vi.fn(), createKeyPool: vi.fn(), updateKeyPool: vi.fn(),
  deleteKeyPool: vi.fn(), copyKeyPool: vi.fn(), assignKeyPool: vi.fn(), unassignKeyPool: vi.fn(),
  getVaultOAuth: vi.fn(), startVaultOAuth: vi.fn(), pollVaultOAuth: vi.fn(), disconnectVaultOAuth: vi.fn(),
}))
vi.mock("@/domains/auth", () => ({ useAuth: () => ({ account: { id: "account-1" } }) }))
vi.mock("@/domains/vault", async (importOriginal) => ({ ...await importOriginal<typeof import("@/domains/vault")>(), ...api }))

const key = {
  id: "k1", provider_type: "tavily", label: "Main", auth_mode: "api_key", status: "active",
  generation: 3, created_at: "", capacity: null, overcommit: true, contention_mode: "equal" as const, pool_count: 1,
}
const pool = {
  id: "pool1", credential_id: "k1", provider_type: "tavily", label: "Research", project_id: "p1", rate: { limit: 60, window_seconds: 60 },
  budget: null, budget_used_usd: 0, operations: ["search", "fetch"], operation_limits: null,
}

beforeEach(() => {
  vi.resetAllMocks()
  api.listVaultKeys.mockResolvedValue([])
  api.listVaultProjects.mockResolvedValue([{ id: "p1", name: "Research", available_providers: ["tavily"] }])
  api.listKeyPools.mockResolvedValue([])
})

describe("KeysPoolsPage", () => {
  it("shows a calm state when the vault endpoint is not available", async () => {
    api.listVaultKeys.mockRejectedValue(new ApiError(404, "Not found", null))
    render(<KeysPoolsPage />)
    expect(await screen.findByText("Keys and pools are not available yet")).toBeInTheDocument()
  })

  it("saves a key with overcommit on and clears a secret after failure", async () => {
    api.createVaultKey.mockRejectedValue(new ApiError(409, "conflict", null))
    render(<KeysPoolsPage />)
    const user = userEvent.setup()
    await user.click((await screen.findAllByRole("button", { name: "Add key" }))[0]!)
    const dialog = screen.getByRole("dialog", { name: "Add key" })
    await user.clear(within(dialog).getByLabelText("Label"))
    await user.type(within(dialog).getByLabelText("Label"), "Main")
    await user.type(within(dialog).getByLabelText("API key"), "secret")
    await user.click(within(dialog).getByRole("button", { name: "Add key" }))
    await screen.findByText("The key did not save. A key with this label exists")
    expect(within(dialog).getByLabelText("API key")).toHaveValue("")
    expect(api.createVaultKey).toHaveBeenCalledWith(expect.objectContaining({ overcommit: true, contention_mode: "equal", secret: "secret" }))
  })

  it("shows provider logos and submits the wire ID for You.com", async () => {
    api.createVaultKey.mockResolvedValue(key)
    render(<KeysPoolsPage />)
    const user = userEvent.setup()
    await user.click((await screen.findAllByRole("button", { name: "Add key" }))[0]!)
    const dialog = screen.getByRole("dialog", { name: "Add key" })
    await user.click(within(dialog).getByRole("combobox", { name: "Provider" }))
    const option = await screen.findByRole("option", { name: "You.com" })
    expect(within(option).getAllByTestId("provider-logo-youcom")[0]).toBeInTheDocument()
    await user.click(option)
    expect(within(dialog).getAllByTestId("provider-logo-youcom")[0]).toBeInTheDocument()
    expect(within(dialog).getByLabelText("Label")).toHaveValue("You.com key")
    await user.clear(within(dialog).getByLabelText("Label"))
    await user.type(within(dialog).getByLabelText("Label"), "You key")
    await user.type(within(dialog).getByLabelText("API key"), "secret")
    await user.click(within(dialog).getByRole("button", { name: "Add key" }))
    await waitFor(() => expect(api.createVaultKey).toHaveBeenCalledWith(expect.objectContaining({ provider_type: "you" })))
  })

  it("shows key policy controls only under Advanced and saves their values", async () => {
    api.createVaultKey.mockResolvedValue(key)
    render(<KeysPoolsPage />)
    const user = userEvent.setup()
    await user.click((await screen.findAllByRole("button", { name: "Add key" }))[0]!)
    const dialog = screen.getByRole("dialog", { name: "Add key" })
    expect(within(dialog).queryByRole("switch", { name: "Overcommit" })).not.toBeInTheDocument()
    await user.click(within(dialog).getByRole("button", { name: "Advanced" }))
    await user.click(within(dialog).getByRole("switch", { name: "Overcommit" }))
    await user.click(within(dialog).getByRole("combobox", { name: "When pools compete" }))
    await user.click(await screen.findByRole("option", { name: "By pool size" }))
    await user.clear(within(dialog).getByLabelText("Label"))
    await user.type(within(dialog).getByLabelText("Label"), "Main")
    await user.type(within(dialog).getByLabelText("API key"), "secret")
    await user.click(within(dialog).getByRole("button", { name: "Add key" }))
    await waitFor(() => expect(api.createVaultKey).toHaveBeenCalledWith(expect.objectContaining({ overcommit: false, contention_mode: "ratio" })))
  })

  it("creates a pool with supported operations and the default rate", async () => {
    api.listVaultKeys.mockResolvedValue([key])
    api.createKeyPool.mockResolvedValue(pool)
    render(<KeysPoolsPage />)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "Actions for Main" }))
    await user.click(await screen.findByRole("button", { name: "Create pool" }))
    const dialog = screen.getByRole("dialog", { name: "Create pool" })
    expect(within(dialog).getByRole("checkbox", { name: "Search" })).toBeChecked()
    expect(within(dialog).getByRole("checkbox", { name: "Fetch" })).toBeChecked()
    await user.click(within(dialog).getByRole("button", { name: "Create pool" }))
    await waitFor(() => expect(api.createKeyPool).toHaveBeenCalledWith("k1", expect.objectContaining({
      project_id: "p1", operations: ["search", "fetch"], rate: { limit: 60, window_seconds: 60 }, budget: null,
    })))
  })

  it("confirms before removing an operation from an assigned pool", async () => {
    api.listVaultKeys.mockResolvedValue([key])
    api.listKeyPools.mockResolvedValue([pool])
    api.updateKeyPool.mockResolvedValue(pool)
    render(<KeysPoolsPage />)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "Pools of Main" }))
    await user.click(screen.getByRole("button", { name: "Actions for Research" }))
    await user.click(await screen.findByRole("button", { name: "Edit pool" }))
    await user.click(screen.getByRole("checkbox", { name: "Fetch" }))
    await user.click(screen.getByRole("button", { name: "Save pool" }))
    expect(api.updateKeyPool).not.toHaveBeenCalled()
    const confirm = screen.getByRole("dialog", { name: "Stop Tavily Fetch" })
    expect(within(confirm).getByText("Tavily leaves the Fetch order of Research. Search stays on")).toBeInTheDocument()
    await user.click(within(confirm).getByRole("button", { name: "Stop Fetch" }))
    await waitFor(() => expect(api.updateKeyPool).toHaveBeenCalledWith("pool1", expect.objectContaining({ operations: ["search"] })))
  })

  it("blocks a pool without an allowed operation", async () => {
    api.listVaultKeys.mockResolvedValue([key])
    render(<KeysPoolsPage />)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "Actions for Main" }))
    await user.click(await screen.findByRole("button", { name: "Create pool" }))
    await user.click(screen.getByRole("checkbox", { name: "Search" }))
    await user.click(screen.getByRole("checkbox", { name: "Fetch" }))
    expect(screen.getByText("Select at least one operation")).toBeInTheDocument()
    expect(within(screen.getByRole("dialog", { name: "Create pool" })).getByRole("button", { name: "Create pool" })).toBeDisabled()
    expect(api.createKeyPool).not.toHaveBeenCalled()
  })

  it("submits a monthly USD budget with cents", async () => {
    api.listVaultKeys.mockResolvedValue([key])
    api.createKeyPool.mockResolvedValue(pool)
    render(<KeysPoolsPage />)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "Actions for Main" }))
    await user.click(await screen.findByRole("button", { name: "Create pool" }))
    expect(screen.queryByText(/Calls with no known cost/)).not.toBeInTheDocument()
    await user.click(screen.getByRole("switch", { name: "Budget" }))
    await user.type(screen.getByLabelText("Budget (USD)"), "12.50")
    await user.click(within(screen.getByRole("dialog", { name: "Create pool" })).getByRole("button", { name: "Create pool" }))
    await waitFor(() => expect(api.createKeyPool).toHaveBeenCalledWith("k1", expect.objectContaining({ budget: { limit: 12.5, period: "month" } })))
  })

  it("saves rate unit and separate operation limits from shared controls", async () => {
    api.listVaultKeys.mockResolvedValue([key])
    api.createKeyPool.mockResolvedValue(pool)
    render(<KeysPoolsPage />)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "Actions for Main" }))
    await user.click(await screen.findByRole("button", { name: "Create pool" }))
    const dialog = screen.getByRole("dialog", { name: "Create pool" })
    expect(within(dialog).getByTestId("provider-logo-tavily")).toBeInTheDocument()
    expect(within(dialog).queryByRole("button", { name: "Advanced" })).not.toBeInTheDocument()
    await user.click(within(dialog).getByRole("combobox", { name: "Rate unit" }))
    await user.click(await screen.findByRole("option", { name: "Per hour" }))
    await user.click(within(dialog).getByRole("switch", { name: "Limit Search and Fetch separately" }))
    await user.clear(within(dialog).getByLabelText("Search requests"))
    await user.type(within(dialog).getByLabelText("Search requests"), "12")
    await user.click(within(dialog).getByRole("button", { name: "Create pool" }))
    await waitFor(() => expect(api.createKeyPool).toHaveBeenCalledWith("k1", expect.objectContaining({
      rate: { limit: 60, window_seconds: 3600 }, operation_limits: { search: 12, fetch: 60 },
    })))
  })

  it("sends the expected generation and clears a stale rotation secret", async () => {
    api.listVaultKeys.mockResolvedValue([key])
    api.rotateVaultKey.mockRejectedValue(new ApiError(409, "conflict", null))
    render(<KeysPoolsPage />)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "Actions for Main" }))
    await user.click(await screen.findByRole("button", { name: "Rotate key" }))
    const dialog = screen.getByRole("dialog", { name: "Rotate key" })
    await user.type(within(dialog).getByLabelText("API key"), "new-secret")
    await user.click(within(dialog).getByRole("button", { name: "Rotate key" }))
    expect(await within(dialog).findByText("The key changed in another window. Reload and try again")).toBeInTheDocument()
    expect(api.rotateVaultKey).toHaveBeenCalledWith("k1", 3, "new-secret")
    expect(within(dialog).getByLabelText("API key")).toHaveValue("")
  })

  it("shows pool and project impact before deleting a key", async () => {
    api.listVaultKeys.mockResolvedValue([key])
    api.listKeyPools.mockResolvedValue([pool])
    render(<KeysPoolsPage />)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "Actions for Main" }))
    await user.click(await screen.findByRole("button", { name: "Delete key" }))
    expect(screen.getByText("Delete this key and its pool. Research loses access to Tavily")).toBeInTheDocument()
    expect(api.deleteVaultKey).not.toHaveBeenCalled()
  })

  it("sorts keys and names each affected project once", async () => {
    api.listVaultKeys.mockResolvedValue([key, { ...key, id: "k2", label: "Brave key", provider_type: "brave" }])
    api.listKeyPools.mockImplementation((id: string) => Promise.resolve(id === "k1" ? [
      pool, { ...pool, id: "pool2", project_id: "p2" }, { ...pool, id: "pool3", project_id: null },
    ] : []))
    api.listVaultProjects.mockResolvedValue([
      { id: "p1", name: "Research", available_providers: ["tavily"] },
      { id: "p2", name: "Docs", available_providers: ["tavily"] },
    ])
    render(<KeysPoolsPage />)
    const user = userEvent.setup()
    const rows = await screen.findAllByRole("row")
    expect(within(rows[1]!).getByText("Brave key")).toBeInTheDocument()
    expect(screen.getByText("3 pools")).toBeInTheDocument()
    expect(screen.getByText("Research, Docs")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Actions for Main" }))
    await user.click(await screen.findByRole("button", { name: "Delete key" }))
    expect(screen.getByText("Delete this key and its 3 pools. Research, Docs lose access to Tavily")).toBeInTheDocument()
  })

  it("copies a pool to the selected project", async () => {
    api.listVaultKeys.mockResolvedValue([key])
    api.listKeyPools.mockResolvedValue([pool])
    api.listVaultProjects.mockResolvedValue([
      { id: "p1", name: "Research", available_providers: ["tavily"] },
      { id: "p2", name: "Docs", available_providers: ["tavily"] },
    ])
    api.copyKeyPool.mockResolvedValue(pool)
    render(<KeysPoolsPage />)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "Pools of Main" }))
    await user.click(screen.getByRole("button", { name: "Actions for Research" }))
    await user.click(await screen.findByRole("button", { name: "Copy to another project" }))
    const dialog = screen.getByRole("dialog", { name: "Copy pool" })
    await user.click(within(dialog).getByRole("combobox", { name: "Copy to project" }))
    await user.click(await screen.findByRole("option", { name: "Docs" }))
    await user.click(within(dialog).getByRole("button", { name: "Copy pool" }))
    await waitFor(() => expect(api.copyKeyPool).toHaveBeenCalledWith("pool1", "p2", "Docs"))
  })

  it("reports deleted pools and projects from the deletion response", async () => {
    const showToast = vi.fn()
    api.listVaultKeys.mockResolvedValue([key])
    api.listKeyPools.mockResolvedValue([pool])
    api.deleteVaultKey.mockResolvedValue({ deleted_pools: [
      { id: "pool1", project_id: "p1" }, { id: "new-pool", project_id: "new-project" },
    ] })
    render(<NotificationsContext.Provider value={{ toasts: [], showToast, dismissToast: vi.fn() }}><KeysPoolsPage /></NotificationsContext.Provider>)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "Actions for Main" }))
    await user.click(await screen.findByRole("button", { name: "Delete key" }))
    await user.click(within(screen.getByRole("dialog", { name: "Delete key Main" })).getByRole("button", { name: "Delete key" }))
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Key deleted. Deleted pools: Research (Research), new-pool (new-project)", "success"))
  })

  it("shows current pool budget usage in the list and edit dialog", async () => {
    api.listVaultKeys.mockResolvedValue([key])
    api.listKeyPools.mockResolvedValue([{ ...pool, budget: { limit: 10, period: "week" }, budget_used_usd: 2.5 }])
    render(<KeysPoolsPage />)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "Pools of Main" }))
    expect(screen.getByText("$2.50 of $10.00 this week")).toBeInTheDocument()
    expect(screen.getByRole("progressbar", { name: "Budget used for Research" })).toHaveAttribute("aria-valuenow", "25")
    await user.click(screen.getByRole("button", { name: "Actions for Research" }))
    await user.click(await screen.findByRole("button", { name: "Edit pool" }))
    const dialog = screen.getByRole("dialog", { name: "Edit pool" })
    expect(within(dialog).getByText("$2.50 of $10.00 this week")).toBeInTheDocument()
    expect(within(dialog).getByText("Calls with no known cost do not count. Resets each period")).toBeInTheDocument()
  })

  it("explains an operation the provider does not support", async () => {
    api.listVaultKeys.mockResolvedValue([{ ...key, provider_type: "brave" }])
    api.listVaultProjects.mockResolvedValue([{ id: "p1", name: "Research", available_providers: ["brave"] }])
    render(<KeysPoolsPage />)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "Actions for Main" }))
    await user.click(await screen.findByRole("button", { name: "Create pool" }))
    expect(screen.queryByRole("checkbox", { name: "Fetch" })).not.toBeInTheDocument()
    expect(screen.getByText("Brave Search has no Fetch")).toBeInTheDocument()
  })

  it("starts the Parallel OAuth flow and polls until connected", async () => {
    api.listVaultKeys.mockResolvedValue([{ ...key, provider_type: "parallel", auth_mode: "oauth" }])
    api.getVaultOAuth.mockResolvedValue({ status: "disconnected" })
    api.startVaultOAuth.mockResolvedValue({ user_code: "ABCD", verification_uri: "https://example.com/", interval: 0.01, expires_in: 60 })
    api.pollVaultOAuth.mockResolvedValue({ status: "connected" })
    render(<KeysPoolsPage />)
    const user = userEvent.setup()
    expect(await screen.findByText("Disconnected")).toBeInTheDocument()
    expect(screen.getByText("—")).toBeInTheDocument()
    await user.click(await screen.findByRole("button", { name: "Actions for Main" }))
    await user.click(await screen.findByRole("button", { name: "Connect" }))
    expect(within(screen.getByRole("dialog", { name: "Connect Parallel" })).getByTestId("provider-logo-parallel")).toBeInTheDocument()
    expect(await screen.findByText("ABCD")).toBeInTheDocument()
    await waitFor(() => expect(api.pollVaultOAuth).toHaveBeenCalled())
    expect(await screen.findByText("Connected")).toBeInTheDocument()
  })
})
