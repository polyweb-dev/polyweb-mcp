import { describe, expect, it } from "vitest"
import type { ProviderConfig } from "@/domains/providers"
import type { DashboardQuota } from "@/domains/dashboard"
import { isStaleRollingQuota, resolveQuota } from "./quotaDetails"

function keenableProvider(overrides: Partial<ProviderConfig> = {}): ProviderConfig {
  return {
    id: "keenable",
    name: "Keenable",
    description: "test",
    baseUrl: "https://api.keenable.ai",
    isCustom: false,
    capabilities: ["search", "fetch"],
    globalEnabled: true,
    searchEnabled: true,
    fetchEnabled: true,
    priority: 2,
    healthStatus: "healthy",
    circuitBreaker: "closed",
    consecutiveFailures: 0,
    latencyP95Ms: 120,
    hasKey: false,
    keyMasked: "",
    keyVaultStatus: "keyless_public",
    quota: {
      used: null,
      limit: null,
      unit: "requests",
      confidence: "observed",
      resetPeriod: "hourly",
      nextReset: null,
      remaining: null,
      remainingPercent: null,
      unitKind: "REQUEST",
      displayUnit: "requests",
      observedAt: null,
      window: "hourly",
    },
    ...overrides,
  }
}

function keylessQuota(resetAt: string): DashboardQuota {
  return {
    provider: "keenable",
    remaining: "999",
    remainingPercent: "99.9",
    limit: "1000",
    observed_at: "2026-09-11T12:00:00Z",
    source: "observed",
    unitKind: "REQUEST",
    displayUnit: "requests",
    resetAt,
    window: "hourly",
  }
}

describe("isStaleRollingQuota", () => {
  it("flags a reset in the past as stale", () => {
    expect(isStaleRollingQuota("2000-01-01T00:00:00Z")).toBe(true)
  })

  it("does not flag a reset in the future", () => {
    expect(isStaleRollingQuota("2999-01-01T00:00:00Z")).toBe(false)
  })

  it("does not flag missing or unparsable resets", () => {
    expect(isStaleRollingQuota(null)).toBe(false)
    expect(isStaleRollingQuota("not-a-date")).toBe(false)
  })
})

describe("resolveQuota keyless detection", () => {
  it("treats keySource none as keyless even without keyless_public vault status", () => {
    const provider = keenableProvider({ keyVaultStatus: "missing", keySource: "none" })
    const { display } = resolveQuota(provider, keylessQuota("2999-01-01T00:00:00Z"))
    expect(display.periodLabel).toBe("Hourly")
    expect(display.detail).toMatch(/keyless/i)
  })
})
