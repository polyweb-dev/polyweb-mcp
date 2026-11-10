import { describe, expect, it } from "vitest"
import type { KeyPool, VaultKey } from "@/domains/vault"
import {
  defaultPoolInputForKey,
  eligibleBulkProjects,
  hasProjectPool,
  keylessKeyInput,
  ownedProviderTypes,
  planBulkProvider,
  planKeylessKey,
  resolveBulkProviders,
} from "./bulkPools"

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
    expect(planBulkProvider(rows, projects, "tavily", "p1").key?.id).toBe("k-tavily")
    expect(planBulkProvider(rows, projects, "exa", "p1").outcome).toMatchObject({
      providerType: "exa", message: expect.stringContaining("no owned key"),
    })
    expect(planBulkProvider(rows, projects, "brave", "p1").outcome).toMatchObject({
      providerType: "brave", message: expect.stringContaining("First, Second"),
    })
    expect(planBulkProvider(rows, projects, "tavily", "p2").outcome.message).toContain("not available")
    expect(planBulkProvider(
      [{ key: key({ id: "k-tavily", provider_type: "tavily" }), pools: [pool({ project_id: "p1" })] }],
      projects, "tavily", "p1",
    ).outcome.message).toContain("already assigned")
  })

  it("plans one keyless key step per reuse/creation/ambiguous outcome", () => {
    const keyless = key({ id: "k-k", provider_type: "keenable", auth_mode: "keyless" })
    expect(planKeylessKey([{ key: keyless, pools: [] }], "keenable").row?.key.id).toBe("k-k")
    expect(planKeylessKey([], "tavily").row).toBeUndefined()
    expect(planKeylessKey([], "tavily").outcome).toBeUndefined()
    const ambiguous = planKeylessKey([
      { key: { ...keyless, id: "a", label: "A" }, pools: [] },
      { key: { ...keyless, id: "b", label: "B" }, pools: [] },
    ], "keenable")
    expect(ambiguous.row).toBeUndefined()
    expect(ambiguous.outcome?.message).toContain("A, B")
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
    expect(eligibleBulkProjects(projects, ["brave", "tavily", "keenable"]).map((project) => project.id)).toEqual(["p1"])
    expect(eligibleBulkProjects(projects, ["brave"]).map((project) => project.id)).toEqual(["p1", "p2"])
  })
})
