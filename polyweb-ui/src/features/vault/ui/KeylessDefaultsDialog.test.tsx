import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import type { KeyPool, VaultKey, VaultProject } from "@/domains/vault"
import { KeylessDefaultsDialog } from "./KeylessDefaultsDialog"
import type { BulkVaultRow } from "../model/bulkPools"

const api = vi.hoisted(() => ({ createVaultKey: vi.fn(), createKeyPool: vi.fn() }))
vi.mock("@/domains/vault", async (importOriginal) => ({ ...await importOriginal<typeof import("@/domains/vault")>(), ...api }))

const projects: VaultProject[] = [
  { id: "p1", name: "Alpha", available_providers: ["keenable", "tavily"] },
]

function vaultKey(overrides: Partial<VaultKey> = {}): VaultKey {
  return {
    id: "key", provider_type: "keenable", label: "Keenable keyless", auth_mode: "keyless",
    status: "active", generation: 1, created_at: "", capacity: null,
    overcommit: true, contention_mode: "equal", pool_count: 0, ...overrides,
  }
}

function keyPool(overrides: Partial<KeyPool> = {}): KeyPool {
  return {
    id: "pool", credential_id: "key", provider_type: "keenable", label: "Keenable",
    project_id: "p1", rate: { limit: null, window_seconds: 60 }, budget: null,
    budget_used_usd: 0, operations: ["search", "fetch"], operation_limits: null, ...overrides,
  }
}

beforeEach(() => {
  vi.resetAllMocks()
  api.createVaultKey.mockImplementation(async (input: { provider_type: string }) =>
    vaultKey({ id: `key-${input.provider_type}`, provider_type: input.provider_type }))
  api.createKeyPool.mockImplementation(async (keyId: string, input: { label: string; project_id: string }) =>
    keyPool({ credential_id: keyId, label: input.label, project_id: input.project_id }))
})

describe("KeylessDefaultsDialog (TASK-000065 AC#2/AC#10)", () => {
  it("creates missing keyless keys and pools with no secret", async () => {
    const user = userEvent.setup()
    const onSaved = vi.fn()
    render(<KeylessDefaultsDialog rows={[]} projects={projects} onClose={vi.fn()} onSaved={onSaved} />)
    expect(screen.queryByLabelText("API key")).not.toBeInTheDocument()
    await user.click(screen.getByRole("combobox", { name: "Project" }))
    await user.click(await screen.findByRole("option", { name: "Alpha" }))
    await user.click(screen.getByRole("button", { name: "Create defaults" }))
    await waitFor(() => expect(api.createVaultKey).toHaveBeenCalledTimes(2))
    for (const call of api.createVaultKey.mock.calls) {
      expect(call[0]).toMatchObject({ auth_mode: "keyless" })
      expect(call[0]).not.toHaveProperty("secret")
    }
    expect(api.createVaultKey).toHaveBeenCalledWith(expect.objectContaining({ provider_type: "keenable" }))
    expect(api.createVaultKey).toHaveBeenCalledWith(expect.objectContaining({ provider_type: "tavily" }))
    await waitFor(() => expect(api.createKeyPool).toHaveBeenCalledTimes(2))
    expect(api.createKeyPool).toHaveBeenCalledWith("key-keenable", expect.objectContaining({ project_id: "p1" }))
    expect(api.createKeyPool).toHaveBeenCalledWith("key-tavily", expect.objectContaining({ project_id: "p1" }))
    expect(onSaved).toHaveBeenCalled()
  })

  it("reuses existing keyless keys and skips already assigned pools", async () => {
    const user = userEvent.setup()
    const rows: BulkVaultRow[] = [{
      key: vaultKey({ id: "key-keenable", provider_type: "keenable" }),
      pools: [keyPool({ id: "pool-k", credential_id: "key-keenable", project_id: "p1" })],
    }]
    render(<KeylessDefaultsDialog rows={rows} projects={projects} onClose={vi.fn()} onSaved={vi.fn()} />)
    await user.click(screen.getByRole("combobox", { name: "Project" }))
    await user.click(await screen.findByRole("option", { name: "Alpha" }))
    await user.click(screen.getByRole("button", { name: "Create defaults" }))
    await waitFor(() => expect(api.createVaultKey).toHaveBeenCalledTimes(1))
    expect(api.createVaultKey).toHaveBeenCalledWith(expect.objectContaining({ provider_type: "tavily" }))
    expect(screen.getByText("Keenable: already assigned")).toBeInTheDocument()
    expect(api.createKeyPool).toHaveBeenCalledTimes(1)
  })

  it("creates nothing on a second run when everything is assigned", async () => {
    const user = userEvent.setup()
    const rows: BulkVaultRow[] = [
      { key: vaultKey({ id: "key-keenable", provider_type: "keenable" }), pools: [keyPool({ credential_id: "key-keenable" })] },
      { key: vaultKey({ id: "key-tavily", provider_type: "tavily", label: "Tavily keyless" }), pools: [keyPool({ id: "pool-t", credential_id: "key-tavily", provider_type: "tavily", label: "Tavily" })] },
    ]
    render(<KeylessDefaultsDialog rows={rows} projects={projects} onClose={vi.fn()} onSaved={vi.fn()} />)
    await user.click(screen.getByRole("combobox", { name: "Project" }))
    await user.click(await screen.findByRole("option", { name: "Alpha" }))
    await user.click(screen.getByRole("button", { name: "Create defaults" }))
    await waitFor(() => expect(screen.getByText("Everything is already assigned. Nothing changed")).toBeInTheDocument())
    expect(api.createVaultKey).not.toHaveBeenCalled()
    expect(api.createKeyPool).not.toHaveBeenCalled()
  })

  it("shows a meaningful error and keeps the dialog open when the key save fails", async () => {
    api.createVaultKey.mockRejectedValue(new Error("boom"))
    const user = userEvent.setup()
    render(<KeylessDefaultsDialog rows={[]} projects={projects} onClose={vi.fn()} onSaved={vi.fn()} />)
    await user.click(screen.getByRole("combobox", { name: "Project" }))
    await user.click(await screen.findByRole("option", { name: "Alpha" }))
    await user.click(screen.getByRole("button", { name: "Create defaults" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("The defaults did not save. Try again")
    expect(screen.getByRole("dialog", { name: "Keyless defaults" })).toBeInTheDocument()
  })
})
