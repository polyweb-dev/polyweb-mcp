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
    expect(await screen.findByText(/Brave Search: 2 keys \(First, Second\)/)).toBeInTheDocument()
    expect(await screen.findByText(/Keenable: created pool/)).toBeInTheDocument()
    // Partial outcome stays open with both lines distinct; nothing auto-saves.
    expect(onSaved).not.toHaveBeenCalled()
    expect(screen.getByRole("button", { name: "Done" })).toBeInTheDocument()
    expect(screen.getByRole("dialog", { name: "Bulk create pools" })).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Done" }))
    expect(onSaved).toHaveBeenCalledWith("Created 1 pool, 1 blocked")
  })

  it("reloads the vault when a partially created run is dismissed without Done", async () => {
    const user = userEvent.setup()
    const onSaved = vi.fn()
    const onClose = vi.fn()
    render(<BulkPoolsDialog rows={rowsOf(
      { key: vaultKey({ id: "k1", label: "First" }), pools: [] },
      { key: vaultKey({ id: "k2", label: "Second" }), pools: [] },
      { key: vaultKey({ id: "k-keenable", provider_type: "keenable", label: "Keenable key", auth_mode: "keyless", capacity: null }), pools: [] },
    )} projects={projects} onClose={onClose} onSaved={onSaved} />)
    await user.click(screen.getByRole("combobox", { name: "Project" }))
    await user.click(await screen.findByRole("option", { name: "Alpha" }))
    await user.click(screen.getByRole("button", { name: "Create 2 pools" }))
    expect(await screen.findByText(/Keenable: created pool/)).toBeInTheDocument()
    await user.keyboard("{Escape}")
    expect(onSaved).toHaveBeenCalledWith("Created 1 pool, 1 blocked")
    expect(onClose).not.toHaveBeenCalled()
  })

  it("creates the missing provider and skips an already assigned one when the API no longer lists it as available", async () => {
    const user = userEvent.setup()
    const onSaved = vi.fn()
    render(<BulkPoolsDialog rows={rowsOf(
      { key: vaultKey({ id: "k-brave", provider_type: "brave" }), pools: [keyPool({ id: "pool-b", credential_id: "k-brave", project_id: "p1" })] },
      { key: vaultKey({ id: "k-keenable", provider_type: "keenable", label: "Keenable key", auth_mode: "keyless", capacity: null }), pools: [] },
    )} projects={[{ id: "p1", name: "Alpha", available_providers: ["keenable"] }]} onClose={vi.fn()} onSaved={onSaved} />)
    await user.click(screen.getByRole("combobox", { name: "Project" }))
    await user.click(await screen.findByRole("option", { name: "Alpha" }))
    await user.click(screen.getByRole("button", { name: "Create 2 pools" }))
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith("Created 1 pool, 1 already assigned"))
    expect(api.createKeyPool).toHaveBeenCalledTimes(1)
    expect(api.createKeyPool).toHaveBeenCalledWith("k-keenable", expect.objectContaining({ project_id: "p1" }))
  })

  it("ignores Cancel, Escape and Close while pool writes are pending", async () => {
    const user = userEvent.setup()
    const onSaved = vi.fn()
    const onClose = vi.fn()
    let releaseBrave: (pool: KeyPool) => void = () => undefined
    let failKeenable = true
    let releaseRetry: (pool: KeyPool) => void = () => undefined
    api.createKeyPool.mockImplementation((keyId: string, input: { label: string; project_id: string }) => {
      const created = keyPool({ credential_id: keyId, label: input.label, project_id: input.project_id })
      if (keyId === "k-brave") return new Promise<KeyPool>((resolve) => { releaseBrave = resolve; })
      if (failKeenable) { failKeenable = false; return Promise.reject(new Error("boom")) }
      return new Promise<KeyPool>((resolve) => { releaseRetry = () => resolve(created) })
    })
    render(<BulkPoolsDialog rows={rowsOf(
      { key: vaultKey({ id: "k-brave", provider_type: "brave", label: "Brave key" }), pools: [] },
      { key: vaultKey({ id: "k-keenable", provider_type: "keenable", label: "Keenable key", auth_mode: "keyless", capacity: null }), pools: [] },
    )} projects={projects} onClose={onClose} onSaved={onSaved} />)
    await user.click(screen.getByRole("combobox", { name: "Project" }))
    await user.click(await screen.findByRole("option", { name: "Alpha" }))
    await user.click(screen.getByRole("button", { name: "Create 2 pools" }))
    await waitFor(() => expect(api.createKeyPool).toHaveBeenCalledTimes(1))
    // First write in flight: every way out of the dialog is inert.
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled()
    await user.keyboard("{Escape}")
    await user.click(screen.getByRole("button", { name: "Close" }))
    expect(onClose).not.toHaveBeenCalled()
    expect(onSaved).not.toHaveBeenCalled()
    expect(screen.getByRole("dialog", { name: "Bulk create pools" })).toBeInTheDocument()
    // The first write settles and the second provider fails: partial progress stays visible.
    releaseBrave(keyPool({ credential_id: "k-brave", label: "Brave Search · Alpha", project_id: "p1" }))
    expect(await screen.findByText("Keenable: did not save — try again")).toBeInTheDocument()
    expect(screen.getByText(/Brave Search: created pool/)).toBeInTheDocument()
    expect(onSaved).not.toHaveBeenCalled()
    // Retry in flight: Done is inert as well.
    await user.click(screen.getByRole("button", { name: "Retry remaining" }))
    await waitFor(() => expect(api.createKeyPool).toHaveBeenCalledTimes(3))
    expect(screen.getByRole("button", { name: "Done" })).toBeDisabled()
    await user.keyboard("{Escape}")
    await user.click(screen.getByRole("button", { name: "Close" }))
    expect(onClose).not.toHaveBeenCalled()
    expect(onSaved).not.toHaveBeenCalled()
    // Settle the retry so nothing is left running; a clean success then saves once.
    releaseRetry(keyPool())
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1))
    expect(onSaved).toHaveBeenCalledWith("Created 2 pools")
    expect(onClose).not.toHaveBeenCalled()
  })

  it("keeps a pool label within 100 characters for a long project name, including a collision suffix", async () => {
    const user = userEvent.setup()
    const longName = "Research programme ".padEnd(100, "x")
    expect(longName).toHaveLength(100)
    const labelsSent: string[] = []
    api.createKeyPool.mockImplementation(async (keyId: string, input: { label: string; project_id: string }) => {
      labelsSent.push(input.label)
      return keyPool({ credential_id: keyId, label: input.label, project_id: input.project_id })
    })
    // Unassigned pool already holds the label the first attempt would pick.
    const first = await (async () => {
      const { unmount } = render(<BulkPoolsDialog rows={rowsOf(
        { key: vaultKey({ id: "k-brave", provider_type: "brave" }), pools: [] },
      )} projects={[{ id: "p9", name: longName, available_providers: ["brave"] }]} onClose={vi.fn()} onSaved={vi.fn()} />)
      await user.click(screen.getByRole("combobox", { name: "Project" }))
      await user.click(await screen.findByRole("option"))
      await user.click(screen.getByRole("button", { name: "Create pool" }))
      await waitFor(() => expect(labelsSent).toHaveLength(1))
      unmount()
      return labelsSent[0] as string
    })()
    expect(first.length).toBeLessThanOrEqual(100)
    expect(first.startsWith("Brave Search · Research programme")).toBe(true)
    render(<BulkPoolsDialog rows={rowsOf(
      { key: vaultKey({ id: "k-brave", provider_type: "brave" }), pools: [keyPool({ label: first, project_id: null })] },
    )} projects={[{ id: "p9", name: longName, available_providers: ["brave"] }]} onClose={vi.fn()} onSaved={vi.fn()} />)
    await user.click(screen.getByRole("combobox", { name: "Project" }))
    await user.click(await screen.findByRole("option"))
    await user.click(screen.getByRole("button", { name: "Create pool" }))
    await waitFor(() => expect(labelsSent).toHaveLength(2))
    const second = labelsSent[1] as string
    expect(second.length).toBeLessThanOrEqual(100)
    expect(second).not.toBe(first)
    expect(second.endsWith("(2)")).toBe(true)
    expect(second.startsWith("Brave Search · Research programme")).toBe(true)
  })

  it("retains completed pools across a failure and creates each pool once on retry", async () => {
    const user = userEvent.setup()
    const onSaved = vi.fn()
    let failedKeenable = false
    api.createKeyPool.mockImplementation(async (keyId: string, input: { label: string; project_id: string }) => {
      if (keyId === "k-keenable" && !failedKeenable) {
        failedKeenable = true
        throw new Error("boom")
      }
      return keyPool({ credential_id: keyId, label: input.label, project_id: input.project_id })
    })
    const onClose = vi.fn()
    render(<BulkPoolsDialog rows={rowsOf(
      { key: vaultKey({ id: "k-brave", provider_type: "brave", label: "Brave key" }), pools: [] },
      { key: vaultKey({ id: "k-keenable", provider_type: "keenable", label: "Keenable key", auth_mode: "keyless", capacity: null }), pools: [] },
    )} projects={projects} onClose={onClose} onSaved={onSaved} />)
    await user.click(screen.getByRole("combobox", { name: "Project" }))
    await user.click(await screen.findByRole("option", { name: "Alpha" }))
    await user.click(screen.getByRole("button", { name: "Create 2 pools" }))
    await waitFor(() => expect(screen.getByText(/Brave Search: created pool/)).toBeInTheDocument())
    expect(await screen.findByText("Keenable: did not save — try again")).toBeInTheDocument()
    // The first attempt created the Brave pool; the retry skips it and
    // creates only Keenable, each pool exactly once.
    await user.click(screen.getByRole("button", { name: "Retry remaining" }))
    await waitFor(() => expect(api.createKeyPool).toHaveBeenCalledTimes(3))
    const braveCalls = api.createKeyPool.mock.calls.filter(([keyId]) => keyId === "k-brave")
    const keenableCalls = api.createKeyPool.mock.calls.filter(([keyId]) => keyId === "k-keenable")
    expect(braveCalls).toHaveLength(1)
    expect(keenableCalls).toHaveLength(2)
    // Completed writes stay reported as created and are not repeated.
    expect(await screen.findByText(/Brave Search: created pool/)).toBeInTheDocument()
    expect(await screen.findByText(/Keenable: created pool/)).toBeInTheDocument()
    expect(onSaved).toHaveBeenCalledWith("Created 2 pools")
  })

  it("labels the pool for the chosen project rather than another project on the same credential", async () => {
    const user = userEvent.setup()
    const onSaved = vi.fn()
    render(<BulkPoolsDialog rows={rowsOf(
      { key: vaultKey({ id: "k-brave", provider_type: "brave", label: "Brave key" }), pools: [keyPool({ project_id: null })] },
    )} projects={[
      { id: "p1", name: "Alpha", available_providers: ["brave"] },
      { id: "p2", name: "Beta", available_providers: ["brave"] },
    ]} onClose={vi.fn()} onSaved={onSaved} />)
    await user.click(screen.getByRole("combobox", { name: "Project" }))
    await user.click(await screen.findByRole("option", { name: "Beta" }))
    await user.click(screen.getByRole("button", { name: "Create pool" }))
    await waitFor(() => expect(api.createKeyPool).toHaveBeenCalledTimes(1))
    expect(api.createKeyPool).toHaveBeenCalledWith("k-brave", expect.objectContaining({
      project_id: "p2",
      label: "Brave Search · Beta",
    }))
    expect(onSaved).toHaveBeenCalledWith("Created 1 pool")
  })

  it("does not reuse a label already held by an unassigned or other-project pool on the credential", async () => {
    const user = userEvent.setup()
    render(<BulkPoolsDialog rows={rowsOf(
      { key: vaultKey({ id: "k-brave", provider_type: "brave" }), pools: [
        keyPool({ id: "pool-a", label: "Brave Search · Beta", project_id: null }),
        keyPool({ id: "pool-b", label: "Brave Search · Alpha", project_id: "p1" }),
      ] },
    )} projects={[
      { id: "p2", name: "Beta", available_providers: ["brave"] },
    ]} onClose={vi.fn()} onSaved={vi.fn()} />)
    await user.click(screen.getByRole("combobox", { name: "Project" }))
    await user.click(await screen.findByRole("option", { name: "Beta" }))
    await user.click(screen.getByRole("button", { name: "Create pool" }))
    await waitFor(() => expect(api.createKeyPool).toHaveBeenCalledTimes(1))
    expect(api.createKeyPool).toHaveBeenCalledWith("k-brave", expect.objectContaining({ label: "Brave Search · Beta (2)" }))
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
    expect(screen.getByText("Everything is already assigned. Nothing changed")).toBeInTheDocument()
  })

  it("names the provider as blocked and keeps the dialog open when creation fails", async () => {
    api.createKeyPool.mockRejectedValue(new Error("boom"))
    const user = userEvent.setup()
    render(<BulkPoolsDialog rows={rowsOf({ key: vaultKey(), pools: [] })} projects={projects} onClose={vi.fn()} onSaved={vi.fn()} />)
    await user.click(screen.getByRole("combobox", { name: "Project" }))
    await user.click(await screen.findByRole("option", { name: "Alpha" }))
    await user.click(screen.getByRole("button", { name: "Create pool" }))
    expect(await screen.findByText("Brave Search: did not save — try again")).toBeInTheDocument()
    expect(screen.getByRole("alert")).toHaveTextContent("No pools were created. Resolve each provider above and try again")
    expect(screen.getByRole("dialog", { name: "Bulk create pools" })).toBeInTheDocument()
  })

  it("requires a project and at least one provider before saving", () => {
    render(<BulkPoolsDialog rows={rowsOf({ key: vaultKey(), pools: [] })} projects={projects} onClose={vi.fn()} onSaved={vi.fn()} />)
    expect(screen.getByRole("button", { name: "Create pool" })).toBeDisabled()
    expect(within(screen.getByRole("dialog", { name: "Bulk create pools" })).getByText("No available projects")).toBeInTheDocument()
  })
})
