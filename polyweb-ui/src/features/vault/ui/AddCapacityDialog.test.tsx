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
    expect(screen.getByRole("dialog", { name: "Add Exa key" })).toBeInTheDocument()
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
    expect(await screen.findByRole("alert")).toHaveTextContent("The key did not save. A key with this label exists")
    expect(screen.getByLabelText("API key")).toHaveValue("")
  })

  it("shows the budget usage below the paired amount and period and saves the pool", async () => {
    render(<AddCapacityDialog item={item} pool={{ ...pool, project_id: "p1" }} projects={[{ id: "p1", name: "Alpha", available_providers: [] }]} onClose={vi.fn()} onSaved={vi.fn()} />)
    const dialog = screen.getByRole("dialog", { name: "Edit pool" })
    expect(within(dialog).getByText("Alpha")).toBeInTheDocument()
    expect(within(dialog).getByText("Main")).toBeInTheDocument()
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

  it.each([null, { limit: 100, window_seconds: 60 }])("preserves an unlimited pool when the key capacity is %s", async (capacity) => {
    render(<AddCapacityDialog item={{ ...item, capacity }} pool={{ ...pool, rate: { limit: null, window_seconds: 60 } }}
      projects={[]} onClose={vi.fn()} onSaved={vi.fn()} />)
    await userEvent.clear(screen.getByLabelText("Pool name"))
    await userEvent.type(screen.getByLabelText("Pool name"), "Renamed")
    await userEvent.click(screen.getByRole("button", { name: "Save pool" }))
    await waitFor(() => expect(api.updateKeyPool).toHaveBeenCalledWith("pool", expect.objectContaining({
      label: "Renamed", rate: { limit: null, window_seconds: 60 },
    })))
  })

  it("saves strict zero rate and budget", async () => {
    render(<AddCapacityDialog item={item} pool={{ ...pool, rate: { limit: 0, window_seconds: 60 }, budget: { limit: 0, period: "month" } }}
      projects={[]} onClose={vi.fn()} onSaved={vi.fn()} />)
    await userEvent.click(screen.getByRole("button", { name: "Save pool" }))
    await waitFor(() => expect(api.updateKeyPool).toHaveBeenCalledWith("pool", expect.objectContaining({
      rate: { limit: 0, window_seconds: 60 }, budget: { limit: 0, period: "month" },
    })))
  })

  it("keeps migrated per-operation windows and unlimited values on edit", async () => {
    const limits = { search: { rate_limit: 20, rate_window_seconds: 60 }, fetch: { rate_limit: null, rate_window_seconds: 3600 } }
    render(<AddCapacityDialog item={{ ...item, provider_type: "tavily" }} pool={{ ...pool, provider_type: "tavily",
      operations: ["search", "fetch"], operation_limits: limits }} projects={[]} onClose={vi.fn()} onSaved={vi.fn()} />)
    await userEvent.clear(screen.getByLabelText("Pool name"))
    await userEvent.type(screen.getByLabelText("Pool name"), "Renamed")
    await userEvent.click(screen.getByRole("button", { name: "Save pool" }))
    await waitFor(() => expect(api.updateKeyPool).toHaveBeenCalledWith("pool", expect.objectContaining({ operation_limits: limits })))
  })

  it("applies an explicit rate unit change to migrated operation limits", async () => {
    const limits = { search: { rate_limit: 20, rate_window_seconds: 60 }, fetch: { rate_limit: null, rate_window_seconds: 3600 } }
    render(<AddCapacityDialog item={{ ...item, provider_type: "tavily" }} pool={{ ...pool, provider_type: "tavily",
      operations: ["search", "fetch"], operation_limits: limits }} projects={[]} onClose={vi.fn()} onSaved={vi.fn()} />)
    await userEvent.click(screen.getByRole("combobox", { name: "Rate unit" }))
    await userEvent.click(await screen.findByRole("option", { name: "Per hour" }))
    await userEvent.click(screen.getByRole("button", { name: "Save pool" }))
    await waitFor(() => expect(api.updateKeyPool).toHaveBeenCalledWith("pool", expect.objectContaining({
      operation_limits: { search: { rate_limit: 20, rate_window_seconds: 3600 }, fetch: limits.fetch },
    })))
  })

  it.each([false, true])("hides budget controls for a free provider (edit: %s)", async (edit) => {
    render(<AddCapacityDialog item={{ ...item, provider_type: "tinyfish" }} pool={edit ? { ...pool, provider_type: "tinyfish" } : undefined}
      projects={[{ id: "p1", name: "Alpha", available_providers: ["tinyfish"] }]} onClose={vi.fn()} onSaved={vi.fn()} />)
    expect(screen.queryByRole("switch", { name: "Budget" })).not.toBeInTheDocument()
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
    const keyDialog = screen.getByRole("dialog", { name: "Add You.com key" })
    expect(within(keyDialog).getByTestId("provider-logo-youcom")).toBeInTheDocument()
    await user.type(within(keyDialog).getByLabelText("API key"), "secret")
    await user.click(within(keyDialog).getByRole("button", { name: "Add key" }))
    const poolDialog = await screen.findByRole("dialog", { name: "Create pool" })
    expect(within(poolDialog).queryByLabelText("Pool name")).not.toBeInTheDocument()
    await user.click(within(poolDialog).getByRole("combobox", { name: "Project" }))
    await user.click(await screen.findByRole("option", { name: "Beta" }))
    await user.click(within(poolDialog).getByRole("switch", { name: "Budget" }))
    await user.type(within(poolDialog).getByLabelText("Budget (USD)"), "5")
    await user.click(within(poolDialog).getByRole("combobox", { name: "Budget period" }))
    await user.click(await screen.findByRole("option", { name: "Per week" }))
    await user.click(within(poolDialog).getByRole("button", { name: "Create pool" }))
    await waitFor(() => expect(api.createKeyPool).toHaveBeenCalledWith("key", expect.objectContaining({
      project_id: "b", label: "Beta", budget: { limit: 5, period: "week" },
    })))
  })

  describe("AddCapacityDialog keyless pool (TASK-000065 AC#2)", () => {
    it("creates a Keenable keyless pool without an API key secret", async () => {
      const user = userEvent.setup()
      render(<AddCapacityDialog provider="keenable" projects={[{ id: "p1", name: "Alpha", available_providers: ["keenable"] }]}
        onClose={vi.fn()} onSaved={vi.fn()} />)
      // Anticipated contract: a keyless provider's key step needs no secret.
      // Current source always shows the API key field for non-OAuth
      // providers and refuses to save without it, so this fails here.
      expect(screen.queryByLabelText("API key")).not.toBeInTheDocument()
      await user.click(screen.getByRole("button", { name: "Add key" }))
      await waitFor(() => expect(api.createVaultKey).toHaveBeenCalledWith(
        expect.objectContaining({ provider_type: "keenable" })
      ))
      expect(api.createVaultKey).not.toHaveBeenCalledWith(
        expect.objectContaining({ secret: expect.anything() })
      )
    })
  })
})
