import { describe, expect, it } from "vitest"
import type { KeyPool, VaultKey } from "@/domains/vault"
import {
  defaultPoolInputForKey,
  defaultPoolLabel,
  eligibleBulkProjects,
  executeProvisionRun,
  hasAssignedPool,
  hasProjectPool,
  judgeOutcomes,
  keylessKeyInput,
  outcomeError,
  ownedProviderTypes,
  planBulkProvider,
  planKeylessProvider,
  reconcileCreated,
  resolveBulkProviders,
  summarizeOutcomes,
} from "./bulkPools"
import type { ProviderOutcome } from "./bulkPools"

function key(overrides: Partial<VaultKey> = {}): VaultKey {
  return {
    id: "key-1", provider_type: "tavily", label: "Tavily key", auth_mode: "api_key",
    status: "active", generation: 1, created_at: "", capacity: null,
    overcommit: true, contention_mode: "equal", pool_count: 0,
    ...overrides,
  }
}

function pool(overrides: Partial<KeyPool> = {}): KeyPool {
  return {
    id: "pool-1", credential_id: "key-1", provider_type: "tavily", label: "Research",
    project_id: "p1", rate: { limit: 60, window_seconds: 60 }, budget: null,
    budget_used_usd: 0, operations: ["search", "fetch"], operation_limits: null,
    ...overrides,
  }
}

describe("bulkPools planner (TASK-000065 AC#10)", () => {
  it("resolves one owned key per selected provider", () => {
    const rows = [{ key: key({ id: "k-tavily", provider_type: "tavily" }), pools: [] }]
    const [status] = resolveBulkProviders(rows, ["tavily"])
    expect(status).toMatchObject({ kind: "ready", providerType: "tavily" })
    if (status.kind === "ready") expect(status.key.id).toBe("k-tavily")
  })

  it("reports a missing key instead of inventing one", () => {
    const [status] = resolveBulkProviders([], ["exa"])
    expect(status).toEqual({ kind: "missing-key", providerType: "exa" })
  })

  it("reports ambiguous keys with their labels instead of picking silently", () => {
    const rows = [
      { key: key({ id: "k1", label: "First" }), pools: [] },
      { key: key({ id: "k2", label: "Second" }), pools: [] },
    ]
    const [status] = resolveBulkProviders(rows, ["tavily"])
    expect(status).toEqual({ kind: "ambiguous-keys", providerType: "tavily", labels: ["First", "Second"] })
  })

  it("plans one bulk provider step per resolution outcome", () => {
    const rows = [
      { key: key({ id: "k-tavily", provider_type: "tavily" }), pools: [] },
      { key: key({ id: "k1", provider_type: "brave", label: "First" }), pools: [] },
      { key: key({ id: "k2", provider_type: "brave", label: "Second" }), pools: [] },
    ]
    const projects = [{ id: "p1", name: "Alpha", available_providers: ["tavily"] }]
    const ready = planBulkProvider(rows, projects, "tavily", "p1")
    expect(ready.kind === "pool" && ready.key.id).toBe("k-tavily")
    expect(planBulkProvider(rows, projects, "exa", "p1")).toMatchObject({
      kind: "skip", outcome: { providerType: "exa", status: "blocked", message: expect.stringContaining("no owned key") },
    })
    expect(planBulkProvider(rows, projects, "brave", "p1")).toMatchObject({
      kind: "skip", outcome: { status: "blocked", message: expect.stringContaining("First, Second") },
    })
    expect(planBulkProvider(rows, projects, "tavily", "p2")).toMatchObject({
      kind: "skip", outcome: { status: "blocked", message: expect.stringContaining("not available") },
    })
    expect(planBulkProvider(
      [{ key: key({ id: "k-tavily", provider_type: "tavily" }), pools: [pool({ project_id: "p1" })] }],
      projects, "tavily", "p1",
    )).toMatchObject({ kind: "skip", outcome: { status: "assigned", message: expect.stringContaining("already assigned") } })
  })

  it("plans one keyless provider step per reuse/creation/ambiguous outcome", () => {
    const keyless = key({ id: "k-k", provider_type: "keenable", auth_mode: "keyless" })
    expect(planKeylessProvider([{ key: keyless, pools: [] }], "keenable", "p1")).toEqual({ kind: "pool", key: keyless })
    expect(planKeylessProvider([], "tavily", "p1")).toEqual({ kind: "create-key" })
    expect(planKeylessProvider([
      { key: { ...keyless, id: "a", label: "A" }, pools: [] },
      { key: { ...keyless, id: "b", label: "B" }, pools: [] },
    ], "keenable", "p1")).toMatchObject({
      kind: "skip", outcome: { status: "blocked", message: expect.stringContaining("A, B") },
    })
  })

  it("lists owned provider types in first-seen order", () => {
    const rows = [
      { key: key({ provider_type: "brave" }), pools: [] },
      { key: key({ provider_type: "tavily" }), pools: [] },
      { key: key({ provider_type: "brave", id: "k2" }), pools: [] },
      { key: key({ provider_type: "keenable", id: "k3" }), pools: [] },
    ]
    expect(ownedProviderTypes(rows)).toEqual(["brave", "tavily", "keenable"])
  })

  it("keeps keyless default pools unlimited and inherits keyed capacity", () => {
    expect(defaultPoolInputForKey(key({ provider_type: "keenable", auth_mode: "keyless" }), "p1")).toMatchObject({
      label: "Keenable", project_id: "p1", rate: { limit: null, window_seconds: 60 }, budget: null,
      operations: ["search", "fetch"], operation_limits: null,
    })
    expect(defaultPoolInputForKey(key({ capacity: { limit: 60, window_seconds: 3600 } }), "p1")).toMatchObject({
      rate: { limit: 60, window_seconds: 3600 },
    })
  })

  it("builds a secret-free keyless key input with the keyless auth mode", () => {
    const input = keylessKeyInput("keenable")
    expect(input).toMatchObject({ provider_type: "keenable", auth_mode: "keyless", overcommit: true, contention_mode: "equal" })
    expect("secret" in input).toBe(false)
  })

  it("detects an already-assigned project pool for idempotent skips", () => {
    const pools = [pool({ project_id: "p1" }), pool({ id: "pool-2", project_id: null })]
    expect(hasProjectPool(pools, "p1")).toBe(true)
    expect(hasProjectPool(pools, "p2")).toBe(false)
    expect(hasProjectPool([], "p1")).toBe(false)
  })

  it("restricts bulk targets to projects available for every provider", () => {
    const projects = [
      { id: "p1", name: "Alpha", available_providers: ["brave", "tavily", "keenable"] },
      { id: "p2", name: "Beta", available_providers: ["brave"] },
    ]
    expect(eligibleBulkProjects(projects, ["brave", "tavily", "keenable"], []).map((project) => project.id)).toEqual(["p1"])
    expect(eligibleBulkProjects(projects, ["brave"], []).map((project) => project.id)).toEqual(["p1", "p2"])
  })

  it("treats an assigned provider as satisfying bulk project eligibility", () => {
    const rows = [{
      key: key({ id: "k-brave", provider_type: "brave" }),
      pools: [pool({ project_id: "p1" })],
    }]
    const projects = [
      { id: "p1", name: "Alpha", available_providers: ["keenable"] },
      { id: "p2", name: "Beta", available_providers: ["brave"] },
    ]
    expect(eligibleBulkProjects(projects, ["brave", "keenable"], rows).map((project) => project.id)).toEqual(["p1"])
  })

  it("judges a run by created, assigned and blocked outcomes", () => {
    const created: ProviderOutcome = { providerType: "keenable", status: "created", message: "Keenable: created pool Keenable · Alpha" }
    const assigned: ProviderOutcome = { providerType: "tavily", status: "assigned", message: "Tavily: already assigned" }
    const blocked: ProviderOutcome = { providerType: "brave", status: "blocked", message: "Brave Search: 2 keys (First, Second) — create from the key row instead" }
    expect(judgeOutcomes([])).toBe("empty")
    expect(judgeOutcomes([created])).toBe("success")
    expect(judgeOutcomes([created, assigned])).toBe("success")
    expect(judgeOutcomes([assigned])).toBe("unchanged")
    expect(judgeOutcomes([created, blocked])).toBe("attention")
    expect(judgeOutcomes([blocked])).toBe("attention")
    expect(outcomeError([assigned])).toBe("Everything is already assigned. Nothing changed")
    expect(outcomeError([blocked, assigned])).toBe("No pools were created. Resolve each provider above and try again")
    expect(outcomeError([created, blocked])).toBeNull()
    expect(summarizeOutcomes([created])).toBe("Created 1 pool")
    expect(summarizeOutcomes([created, { ...created, providerType: "exa" }])).toBe("Created 2 pools")
    expect(summarizeOutcomes([created, assigned, blocked])).toBe("Created 1 pool, 1 already assigned, 1 blocked")
    expect(summarizeOutcomes([assigned])).toBe("Created 0 pools, 1 already assigned")
  })

  it("reconciles created keys and pools onto the right key idempotently", () => {
    const rows = [{ key: key({ id: "k-tavily", provider_type: "tavily" }), pools: [] as KeyPool[] }]
    expect(reconcileCreated(rows, { keyId: "k-tavily", pool: pool({ id: "pool-2" }) })[0]?.pools.map((entry) => entry.id)).toEqual(["pool-2"])
    expect(reconcileCreated(rows, { key: key({ id: "k2" }) })).toHaveLength(2)
    expect(reconcileCreated(rows, { key: key({ id: "k-tavily" }) })).toHaveLength(1)
  })

  it("generates a project-scoped pool label that avoids credential label collisions", () => {
    expect(defaultPoolLabel("brave", "Alpha", [])).toBe("Brave Search · Alpha")
    expect(defaultPoolLabel("tavily", "Beta", ["Tavily · Beta"])).toBe("Tavily · Beta (2)")
    expect(defaultPoolLabel("tavily", "Beta", ["Tavily · Beta", "Tavily · Beta (2)"])).toBe("Tavily · Beta (3)")
    expect(defaultPoolLabel("keenable", "Alpha", ["Keenable · Beta"])).toBe("Keenable · Alpha")
  })

  it("checks an existing assignment before project availability (real API shape)", () => {
    // The API excludes already-assigned providers from available_providers,
    // so the assigned check must come first to report accurately.
    const rows = [{
      key: key({ id: "k-brave", provider_type: "brave", label: "Brave key" }),
      pools: [pool({ id: "pool-b", credential_id: "k-brave", provider_type: "brave", label: "Brave Search · Alpha", project_id: "p1" })],
    }]
    const projects = [{ id: "p1", name: "Alpha", available_providers: ["keenable"] }]
    expect(planBulkProvider(rows, projects, "brave", "p1")).toMatchObject({ kind: "skip", outcome: { status: "assigned" } })
    expect(planBulkProvider(rows, projects, "keenable", "p1")).toMatchObject({
      kind: "skip", outcome: { providerType: "keenable", message: expect.stringContaining("no owned key") },
    })
  })

  it("skips a keyless default when a keyed pool is already assigned, without blocking distinct keyless creation", () => {
    const keyed = key({ id: "k-tavily", provider_type: "tavily", label: "Tavily key" })
    const assigned = [{ key: keyed, pools: [pool({ id: "pool-t", credential_id: "k-tavily", project_id: "p1" })] }]
    expect(hasAssignedPool(assigned, "tavily", "p1")).toBe(true)
    expect(planKeylessProvider(assigned, "tavily", "p1")).toMatchObject({ kind: "skip", outcome: { status: "assigned" } })
    const unassignedKey = [{ key: keyed, pools: [pool({ id: "pool-u", credential_id: "k-tavily", project_id: null })] }]
    expect(hasAssignedPool(unassignedKey, "tavily", "p1")).toBe(false)
    expect(planKeylessProvider(unassignedKey, "tavily", "p1")).toEqual({ kind: "create-key" })
  })

  it("treats an assignment on any key of the provider as already assigned before reporting ambiguity", () => {
    const rows = [
      { key: key({ id: "k1", provider_type: "brave", label: "First" }), pools: [pool({ project_id: "p1" })] },
      { key: key({ id: "k2", provider_type: "brave", label: "Second" }), pools: [] },
    ]
    expect(planBulkProvider(rows, [{ id: "p1", name: "Alpha", available_providers: [] }], "brave", "p1"))
      .toMatchObject({ kind: "skip", outcome: { status: "assigned" } })
  })

  it("runs each provider once: creates keys, labels per credential, skips completed providers on retry", async () => {
    const created: unknown[] = []
    const clients = {
      createKey: async (input: { provider_type: string }) =>
        key({ id: `new-${input.provider_type}`, provider_type: input.provider_type, auth_mode: "keyless" }),
      createPool: async (keyId: string, input: { label: string }) => {
        created.push([keyId, input.label])
        return pool({ id: `pool-${created.length}`, credential_id: keyId, label: input.label })
      },
    }
    const hooks = { publish: () => undefined, reconcile: () => undefined }
    const base = {
      mode: "defaults" as const, rows: [], projects: [], providerTypes: ["keenable", "tavily"],
      projectId: "p1", projectName: "Alpha", kept: [] as ProviderOutcome[],
    }
    await executeProvisionRun(base, hooks, clients)
    expect(created).toEqual([["new-keenable", "Keenable · Alpha"], ["new-tavily", "Tavily · Alpha"]])
    await executeProvisionRun({
      ...base,
      kept: [{ providerType: "keenable", status: "created", message: "Keenable: created pool" }],
    }, hooks, clients)
    expect(created).toHaveLength(3)
    expect(created[2]).toEqual(["new-tavily", "Tavily · Alpha"])
  })
})
