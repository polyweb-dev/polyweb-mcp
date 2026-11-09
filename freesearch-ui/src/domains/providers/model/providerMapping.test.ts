import { describe, expect, it } from "vitest"
import { providerStatus } from "@/test/backendFixtures"
import { mapProviderRows, updateProviderFromWire } from "./providerMapping"

describe("provider real-call health mapping", () => {
  it("keeps catalog response order on reads and updates without system priorities", () => {
    const rows = [providerStatus("exa"), providerStatus("brave")]
    const initial = mapProviderRows(rows)
    expect(initial.map((provider) => provider.id)).toEqual(["exa", "brave"])
    expect(initial[0]).not.toHaveProperty("priority")

    const updated = updateProviderFromWire(initial, providerStatus("brave", { enabled: false }))
    expect(updated.map((provider) => provider.id)).toEqual(["exa", "brave"])
    expect(updated[1]?.globalEnabled).toBe(false)
    expect(updated[1]).not.toHaveProperty("priority")
  })

  it("preserves the checked-at time and live-key health even without a legacy secret", () => {
    const row = { ...providerStatus("brave", { health: "healthy", secret_presence: "missing" }), health_checked_at: "2026-11-08T09:00:00Z" }
    expect(mapProviderRows([row])[0]).toMatchObject({ healthStatus: "healthy", healthCheckedAt: row.health_checked_at })
  })

  it("keeps unknown, absent or malformed observation times null", () => {
    for (const health_checked_at of [null, "invalid", undefined]) {
      expect(mapProviderRows([{ ...providerStatus("brave"), health_checked_at }])[0]?.healthCheckedAt).toBeNull()
    }
  })

  it("updates health and timestamp together on a subsequent provider response", () => {
    const initial = mapProviderRows([providerStatus("brave")])
    const row = { ...providerStatus("brave", { health: "degraded" }), health_checked_at: "2026-11-08T09:00:00Z" }
    expect(updateProviderFromWire(initial, row)[0]).toMatchObject({ healthStatus: "degraded", healthCheckedAt: row.health_checked_at })
  })

  it("maps per-operation prices on reads and updates", () => {
    const row = { ...providerStatus("firecrawl"), call_cost_usd: { search: "0.0076", fetch: "0.0038" } }
    const initial = mapProviderRows([row])
    expect(initial[0]?.callCostUsd).toEqual(row.call_cost_usd)
    const updated = { ...row, call_cost_usd: { search: "0", fetch: null } }
    expect(updateProviderFromWire(initial, updated)[0]?.callCostUsd).toEqual(updated.call_cost_usd)
  })

  it("takes keyless availability and prices only from the catalog response", () => {
    const row = { ...providerStatus("tavily"), call_cost_usd: { search: "0.008", fetch: "0.0016" }, keyless_call_cost_usd: { search: "0", fetch: "0" } }
    const initial = mapProviderRows([row])
    expect(initial[0]?.capabilities).toContain("keyless_tier")
    expect(initial[0]?.keylessCallCostUsd).toEqual(row.keyless_call_cost_usd)
    expect(updateProviderFromWire(initial, { ...row, keyless_call_cost_usd: {} })[0]?.capabilities).not.toContain("keyless_tier")
    expect(mapProviderRows([providerStatus("keenable")])[0]?.capabilities).not.toContain("keyless_tier")
  })
})
