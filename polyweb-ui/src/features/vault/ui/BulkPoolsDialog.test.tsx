import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import type { KeyPool, VaultKey, VaultProject } from "@/domains/vault"
import { BulkPoolsDialog } from "./BulkPoolsDialog"
import type { BulkVaultRow } from "../model/bulkPools"

const api = vi.hoisted(() => ({ createKeyPool: vi.fn() }))
vi.mock("@/domains/vault", async (importOriginal) => ({ ...await importOriginal<typeof import("@/domains/vault")>(), ...api }))

function vaultKey(overrides: Partial<VaultKey> = {}): VaultKey {
  return {
    id: "key", provider_type: "brave", label: "Main", auth_mode: "api_key", status: "active",
    generation: 1, created_at: "", capacity: { limit: 60, window_seconds: 60 },
    overcommit: true, contention_mode: "equal", pool_count: 0, ...overrides,
  }
}

function keyPool(overrides: Partial<KeyPool> = {}): KeyPool {
  return {
    id: "pool", credential_id: "key", provider_type: "brave", label: "Research", project_id: null,
    rate: { limit: 60, window_seconds: 60 }, budget: null, budget_used_usd: 0,
    operations: ["search"], operation_limits: null, ...overrides,
  }
}

const projects: VaultProject[] = [
  { id: "p1", name: "Alpha", available_providers: ["brave", "keenable"] },
]

function rowsOf(...rows: BulkVaultRow[]): BulkVaultRow[] {
  return rows
}

beforeEach(() => {
  vi.resetAllMocks()
  api.createKeyPool.mockImplementation(async (keyId: string, input: { label: string; project_id: string }) =>
    keyPool({ credential_id: keyId, label: input.label, project_id: input.project_id }))
})

describe("BulkPoolsDialog (TASK-000065 AC#10)", () => {
  it("creates one pool per provider on its owned key for the chosen project", async () => {
    const user = userEvent.setup()
    const onSaved = vi.fn()
    render(<BulkPoolsDialog rows={rowsOf(
      { key: vaultKey({ id: "k-brave", provider_type: "brave", label: "Brave key" }), pools: [] },
      { key: vaultKey({ id: "k-keenable", provider_type: "keenable", label: "Keenable key", auth_mode: "keyless", capacity: null }), pools: [] },
    )} projects={projects} onClose={vi.fn()} onSaved={onSaved} />)
    await user.click(screen.getByRole("combobox", { name: "Project" }))
    await user.click(await screen.findByRole("option", { name: "Alpha" }))
    expect(screen.getByRole("checkbox", { name: "Brave Search" })).toBeChecked()
    await user.click(screen.getByRole("button", { name: "Create 2 pools" }))
    await waitFor(() => expect(api.createKeyPool).toHaveBeenCalledTimes(2))
    expect(api.createKeyPool).toHaveBeenCalledWith("k-brave", expect.objectContaining({ project_id: "p1", budget: null }))
    expect(api.createKeyPool).toHaveBeenCalledWith("k-keenable", expect.objectContaining({
      project_id: "p1", rate: { limit: null, window_seconds: 60 }, operations: ["search", "fetch"],
    }))
    expect(onSaved).toHaveBeenCalledWith("Created 2 pools")
  })

  it("reports an ambiguous provider by name while creating the rest", async () => {
    const user = userEvent.setup()
    const onSaved = vi.fn()
    render(<BulkPoolsDialog rows={rowsOf(
      { key: vaultKey({ id: "k1", label: "First" }), pools: [] },
      { key: vaultKey({ id: "k2", label: "Second" }), pools: [] },
      { key: vaultKey({ id: "k-keenable", provider_type: "keenable", label: "Keenable key", auth_mode: "keyless", capacity: null }), pools: [] },
    )} projects={projects} onClose={vi.fn()} onSaved={onSaved} />)
    await user.click(screen.getByRole("combobox", { name: "Project" }))
    await user.click(await screen.findByRole("option", { name: "Alpha" }))
    await user.click(screen.getByRole("button", { name: "Create 2 pools" }))
    await waitFor(() => expect(api.createKeyPool).toHaveBeenCalledTimes(1))
    expect(api.createKeyPool).toHaveBeenCalledWith("k-keenable", expect.anything())
    expect(screen.getByText(/Brave Search: 2 keys \(First, Second\)/)).toBeInTheDocument()
    expect(onSaved).toHaveBeenCalledWith(expect.stringContaining("Created 1"))
  })

  it("skips an already assigned provider without duplicating it", async () => {
    const user = userEvent.setup()
    render(<BulkPoolsDialog rows={rowsOf(
      { key: vaultKey({ id: "k-brave", provider_type: "brave" }), pools: [keyPool({ project_id: "p1" })] },
    )} projects={projects} onClose={vi.fn()} onSaved={vi.fn()} />)
    await user.click(screen.getByRole("combobox", { name: "Project" }))
    await user.click(await screen.findByRole("option", { name: "Alpha" }))
    await user.click(screen.getByRole("button", { name: "Create pool" }))
    await waitFor(() => expect(screen.getByText("Brave Search: already assigned")).toBeInTheDocument())
    expect(api.createKeyPool).not.toHaveBeenCalled()
    expect(screen.getByText("No pools were created. Resolve each provider above and try again")).toBeInTheDocument()
  })

  it("shows a meaningful error and keeps the dialog open when creation fails", async () => {
    api.createKeyPool.mockRejectedValue(new Error("boom"))
    const user = userEvent.setup()
    render(<BulkPoolsDialog rows={rowsOf({ key: vaultKey(), pools: [] })} projects={projects} onClose={vi.fn()} onSaved={vi.fn()} />)
    await user.click(screen.getByRole("combobox", { name: "Project" }))
    await user.click(await screen.findByRole("option", { name: "Alpha" }))
    await user.click(screen.getByRole("button", { name: "Create pool" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("The pools did not save. Try again")
    expect(screen.getByRole("dialog", { name: "Bulk create pools" })).toBeInTheDocument()
  })

  it("requires a project and at least one provider before saving", () => {
    render(<BulkPoolsDialog rows={rowsOf({ key: vaultKey(), pools: [] })} projects={projects} onClose={vi.fn()} onSaved={vi.fn()} />)
    expect(screen.getByRole("button", { name: "Create pool" })).toBeDisabled()
    expect(within(screen.getByRole("dialog", { name: "Bulk create pools" })).getByText("No available projects")).toBeInTheDocument()
  })
})
