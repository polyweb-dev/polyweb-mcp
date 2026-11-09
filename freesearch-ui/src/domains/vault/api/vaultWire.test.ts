import { describe, expect, it } from "vitest"
import { decodeKeyDeleteResult, decodeKeyPool, decodeOAuthDevice, decodeOAuthStatus, decodeVaultKey, decodeVaultProjects } from "./vaultWire"

const pool = {
  id: "pool-1", credential_id: "key-1", project_id: "project-1", provider_type: "tavily",
  label: "Research", rate: { limit: 100, window_seconds: 60 }, budget: { limit: 12.5, period: "month" },
  budget_used_usd: 1.234567, operations: ["search", "fetch"], operation_limits: { search: 30 },
}

describe("vault response decoders", () => {
  it("retains backend pool identity and decimal budget usage", () => {
    expect(decodeKeyPool(pool)).toEqual(pool)
    expect(decodeKeyPool({ ...pool, project_id: null, budget: null, budget_used_usd: 0 }))
      .toMatchObject({ project_id: null, budget: null, budget_used_usd: 0 })
  })

  it("retains migrated operation windows and unlimited limits", () => {
    const limits = { search: { rate_limit: 20, rate_window_seconds: 60 }, fetch: { rate_limit: null, rate_window_seconds: 3600 } }
    expect(decodeKeyPool({ ...pool, operation_limits: limits }).operation_limits).toEqual(limits)
  })

  it("rejects missing or invalid budget usage and invalid budget periods", () => {
    expect(() => decodeKeyPool({ ...pool, budget_used_usd: undefined })).toThrow()
    expect(() => decodeKeyPool({ ...pool, budget_used_usd: "1.2" })).toThrow()
    expect(() => decodeKeyPool({ ...pool, budget: { limit: 5, period: "year" } })).toThrow()
  })

  it("decodes deleted pools including unassigned pools", () => {
    const result = { deleted_pools: [{ id: "pool-1", project_id: "project-1" }, { id: "pool-2", project_id: null }] }
    expect(decodeKeyDeleteResult(result)).toEqual(result)
    expect(() => decodeKeyDeleteResult({ deleted_pools: [{ id: "pool-1" }] })).toThrow()
  })

  it("decodes backend key, project and OAuth projections without secret fields", () => {
    const key = { id: "key-1", provider_type: "parallel", label: "Main", auth_mode: "oauth", status: "active",
      generation: 1, created_at: "2026-01-01T00:00:00Z", capacity: { limit: null, window_seconds: 60 },
      overcommit: true, contention_mode: "equal", pool_count: 1 }
    expect(decodeVaultKey({ ...key, rotated_at: null, health: null, secret: "hidden" })).toEqual(key)
    expect(decodeVaultProjects([{ id: "project-1", name: "Research", available_providers: ["parallel"] }]))
      .toEqual([{ id: "project-1", name: "Research", available_providers: ["parallel"] }])
    const device = { user_code: "ABCD", verification_uri: "https://example.com/device", interval: 5, expires_in: 600 }
    expect(decodeOAuthDevice(device)).toEqual(device)
    expect(decodeOAuthStatus({ credential_id: "key-1", status: "pending", interval: 5, scopes: null,
      access_expires_at: null, connected_at: null, refreshed_at: null, disconnected_at: null, last_error_code: null }))
      .toEqual({ status: "pending", interval: 5 })
  })
})
