import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import type { KeyPool, VaultKey } from "@/domains/vault"
import { ApiError } from "@/shared/api/http"
import { AddCapacityDialog } from "./AddCapacityDialog"

const api = vi.hoisted(() => ({ createVaultKey: vi.fn(), createKeyPool: vi.fn(), updateKeyPool: vi.fn() }))
vi.mock("@/domains/vault", async (importOriginal) => ({ ...await importOriginal<typeof import("@/domains/vault")>(), ...api }))
vi.mock("../model/useFreeProvider", () => ({ useFreeProvider: (provider: string) => provider === "tinyfish" }))

const item: VaultKey = {
  id: "key", provider_type: "brave", label: "Main", auth_mode: "api_key", status: "active",
  generation: 1, created_at: "", capacity: null, overcommit: true, contention_mode: "equal", pool_count: 0,
}
const pool: KeyPool = {
  id: "pool", credential_id: "key", provider_type: "brave", label: "Research", project_id: null,
  rate: { limit: 60, window_seconds: 60 }, budget: { limit: 20, period: "month" }, budget_used_usd: 0,
  operations: ["search"], operation_limits: null,
}
beforeEach(() => vi.resetAllMocks())

describe("AddCapacityDialog", () => {
  it("explains the inline key step and marks empty required fields", async () => {
    render(<AddCapacityDialog provider="exa" projects={[{ id: "p1", name: "Gamma - Admins only", available_providers: ["exa"] }]}
      onClose={vi.fn()} onSaved={vi.fn()} />)
    expect(screen.getByRole("dialog", { name: "Add key" })).toBeInTheDocument()
    expect(screen.getByText("You have no Exa key yet. Add one, then create the pool for Gamma - Admins only")).toBeInTheDocument()
    expect(screen.getByLabelText("Label")).toHaveValue("Exa key")
    await userEvent.clear(screen.getByLabelText("Label"))
    await userEvent.click(screen.getByRole("button", { name: "Add key" }))
    expect(screen.getByLabelText("Label")).toHaveAccessibleDescription("Enter a label")
    expect(screen.getByLabelText("API key")).toHaveAccessibleDescription("Enter the API key")
    expect(api.createVaultKey).not.toHaveBeenCalled()
  })

  it("shows the same duplicate-label error as the account key dialog", async () => {
    api.createVaultKey.mockRejectedValue(new ApiError(409, "duplicate", null))
    render(<AddCapacityDialog provider="exa" projects={[]} onClose={vi.fn()} onSaved={vi.fn()} />)
    await userEvent.type(screen.getByLabelText("API key"), "secret")
    await userEvent.click(screen.getByRole("button", { name: "Add key" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("The key did not save. A key with this label exists.")
    expect(screen.getByLabelText("API key")).toHaveValue("")
  })

  it("shows the budget usage below the paired amount and period and saves the pool", async () => {
    render(<AddCapacityDialog item={item} pool={pool} projects={[]} onClose={vi.fn()} onSaved={vi.fn()} />)
    expect(screen.getByLabelText("Budget (USD)")).toHaveValue(20)
    expect(screen.getByRole("combobox", { name: "Budget period" })).toHaveTextContent("Per month")
    expect(screen.getByText("$0.00 of $20.00 this month")).toBeInTheDocument()
    expect(screen.getByText("Calls with no known cost do not count. Resets each period")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Advanced" })).not.toBeInTheDocument()
    expect(screen.getByLabelText("Request rate")).toHaveValue(60)
    expect(screen.getByText("Brave Search has no Fetch")).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Save pool" }))
    await waitFor(() => expect(api.updateKeyPool).toHaveBeenCalledWith("pool", expect.objectContaining({ budget: { limit: 20, period: "month" } })))
  })

  it.each([false, true])("hides budget controls for a free provider (edit: %s)", async (edit) => {
    render(<AddCapacityDialog item={{ ...item, provider_type: "tinyfish" }} pool={edit ? { ...pool, provider_type: "tinyfish" } : undefined}
      projects={[{ id: "p1", name: "Alpha", available_providers: ["tinyfish"] }]} onClose={vi.fn()} onSaved={vi.fn()} />)
    expect(screen.queryByRole("switch", { name: "Add a budget" })).not.toBeInTheDocument()
    expect(screen.queryByLabelText("Budget (USD)")).not.toBeInTheDocument()
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument()
    expect(screen.getByRole("switch", { name: "Limit Search and Fetch separately" })).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: edit ? "Save pool" : "Create pool" }))
    await waitFor(() => expect(edit ? api.updateKeyPool : api.createKeyPool).toHaveBeenCalledWith(edit ? "pool" : "key", expect.objectContaining({ budget: null })))
  })

  it("adds an inline key and creates a pool for the selected project", async () => {
    api.createVaultKey.mockResolvedValue({
      id: "key", provider_type: "you", label: "You.com key", auth_mode: "api_key",
      status: "active", capacity: null, overcommit: true, contention_mode: "equal",
    })
    api.createKeyPool.mockResolvedValue({})
    render(<AddCapacityDialog provider="you" projects={[
      { id: "a", name: "Alpha", available_providers: ["you"] },
      { id: "b", name: "Beta", available_providers: ["you"] },
    ]} onClose={vi.fn()} onSaved={vi.fn()} />)
    const user = userEvent.setup()
    const keyDialog = screen.getByRole("dialog", { name: "Add key" })
    expect(within(keyDialog).getByTestId("provider-logo-youcom")).toBeInTheDocument()
    await user.type(within(keyDialog).getByLabelText("API key"), "secret")
    await user.click(within(keyDialog).getByRole("button", { name: "Add key" }))
    const poolDialog = await screen.findByRole("dialog", { name: "Create pool from You.com key" })
    await user.click(within(poolDialog).getByRole("combobox", { name: "Project" }))
    await user.click(await screen.findByRole("option", { name: "Beta" }))
    await user.click(within(poolDialog).getByRole("switch", { name: "Add a budget" }))
    await user.type(within(poolDialog).getByLabelText("Budget (USD)"), "5")
    await user.click(within(poolDialog).getByRole("combobox", { name: "Budget period" }))
    await user.click(await screen.findByRole("option", { name: "Per week" }))
    await user.click(within(poolDialog).getByRole("button", { name: "Create pool" }))
    await waitFor(() => expect(api.createKeyPool).toHaveBeenCalledWith("key", expect.objectContaining({
      project_id: "b", label: "Beta - You.com", budget: { limit: 5, period: "week" },
    })))
  })
})
