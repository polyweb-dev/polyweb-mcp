import { describe, expect, it } from "vitest"
import type { ProviderConfig } from "@/domains/providers"
import type { DashboardQuota } from "@/domains/dashboard"
import { isStaleRollingQuota, quotaCaptionFor, quotaValues, resolveQuota } from "./quotaDetails"

function keenableProvider(overrides: Partial<ProviderConfig> = {}): ProviderConfig {
  return {
    id: "keenable",
    name: "Keenable",
    description: "test",
    baseUrl: "https://api.keenable.ai",
    isCustom: false,
    capabilities: ["search", "fetch"],
    enableMask: 7,
    supportMask: 7,
    globalEnabled: true,
    searchEnabled: true,
    fetchEnabled: true,
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

function quotaProvider(
  id: string,
  quotaOverrides: Partial<ProviderConfig["quota"]> = {},
  overrides: Partial<ProviderConfig> = {}
): ProviderConfig {
  return {
    id,
    name: id,
    description: "test",
    baseUrl: "https://api.test",
    isCustom: false,
    capabilities: ["search", "fetch"],
    enableMask: 7,
    supportMask: id === "brave" ? 3 : 7,
    globalEnabled: true,
    searchEnabled: true,
    fetchEnabled: true,
    healthStatus: "healthy",
    circuitBreaker: "closed",
    consecutiveFailures: 0,
    latencyP95Ms: 120,
    hasKey: true,
    keyMasked: "",
    keyVaultStatus: "configured",
    quota: {
      used: null,
      limit: null,
      unit: "units",
      confidence: "estimated",
      resetPeriod: "monthly",
      nextReset: null,
      remaining: null,
      remainingPercent: null,
      unitKind: "USD",
      displayUnit: "USD",
      observedAt: null,
      window: "monthly",
      ...quotaOverrides,
    },
    ...overrides,
  }
}

function snapshot(
  provider: string,
  overrides: Partial<DashboardQuota> = {}
): DashboardQuota {
  return {
    provider,
    remaining: null,
    remainingPercent: null,
    limit: null,
    observed_at: "2026-09-11T12:00:00Z",
    source: "estimated",
    unitKind: "USD",
    displayUnit: "USD",
    resetAt: null,
    window: null,
    ...overrides,
  }
}

/**
 * Slice 2.2 characterization: latest-snapshot-as-whole precedence.
 * A null-valued latest snapshot must NOT resurrect older provider-base
 * balances (quotaValues:32 whole-selection contract).
 */
describe("quotaValues latest-snapshot-as-whole precedence", () => {
  it("does not resurrect base balances when latest carries nulls", () => {
    const provider = quotaProvider("parallel", {
      remaining: "99.99",
      remainingPercent: "99.9",
      limit: "100.00",
      confidence: "observed",
      observedAt: "2026-09-10T12:00:00Z",
      nextReset: "2026-10-01T00:00:00Z",
    })
    const latest = snapshot("parallel", { source: "authoritative" })
    const values = quotaValues(provider, latest)
    expect(values.remaining).toBeNull()
    expect(values.limit).toBeNull()
    expect(values.remainingPercent).toBeNull()
    expect(values.confidence).toBe("authoritative")
    expect(values.resetAt).toBeNull()
  })

  it("falls back to base values only when latest is absent", () => {
    const provider = quotaProvider("parallel", {
      remaining: "99.99",
      limit: "100.00",
      confidence: "observed",
      observedAt: "2026-09-10T12:00:00Z",
      nextReset: "2026-10-01T00:00:00Z",
    })
    const values = quotaValues(provider, undefined)
    expect(values.remaining).toBe("99.99")
    expect(values.limit).toBe("100.00")
    expect(values.confidence).toBe("observed")
    expect(values.resetAt).toBe("2026-10-01T00:00:00Z")
  })
})

/** Slice 2.2 characterization: resolveQuota keyless/OAuth state. */
describe("resolveQuota OAuth pairing branches", () => {
  it("reads paired-but-unused Parallel as Balance pending, not Budget not configured", () => {
    const provider = quotaProvider("parallel")
    const latest = snapshot("parallel")
    const paired = resolveQuota(provider, latest, true)
    expect(paired.display.headline).toBe("Balance pending")
    expect(paired.display.periodLabel).toBe("Account balance")
    expect(paired.display.nativeValue).toBe("OAuth connected")
    const unpaired = resolveQuota(provider, latest, false)
    expect(unpaired.display.headline).toBe("Budget not configured")
    expect(unpaired.display.periodLabel).toBe("Monthly")
  })

  it("reads an authoritative remaining-only snapshot as a balance", () => {
    const provider = quotaProvider("parallel")
    const latest = snapshot("parallel", {
      remaining: "3.75",
      source: "authoritative",
    })
    const { display } = resolveQuota(provider, latest, false)
    expect(display.headline).toBe("Balance available")
    expect(display.periodLabel).toBe("Account balance")
    expect(display.nativeValue).toBe("3.75/— USD")
    expect(display.remainingPercent).toBeNull()
  })
})

/** Slice 2.2 characterization: unknown-limit/hourly rendering + native decimals. */
describe("resolveQuota unknown-limit and hourly rendering", () => {
  it("reads You.com remaining USD as an account balance with verbatim decimals", () => {
    const provider = quotaProvider("youcom")
    const latest = snapshot("youcom", { remaining: "199.77" })
    const { display } = resolveQuota(provider, latest, false)
    expect(display.headline).toBe("Balance available")
    expect(display.periodLabel).toBe("Account balance")
    expect(display.nativeValue).toBe("199.77/— USD")
    expect(display.remainingPercent).toBeNull()
  })

  it("names a Brave unknown limit without inventing a percentage", () => {
    const provider = quotaProvider("brave", {
      unitKind: "REQUEST",
      displayUnit: "requests",
    })
    const latest = snapshot("brave", {
      remaining: "950",
      limit: null,
      unitKind: "REQUEST",
      displayUnit: "requests",
      source: "observed",
    })
    const { display } = resolveQuota(provider, latest, false)
    expect(display.headline).toBe("Limit unavailable")
    expect(display.nativeValue).toBe("950/— requests")
    expect(display.remainingPercent).toBeNull()
  })

  it("keeps a keyless Hourly window distinct from monthly quota", () => {
    const provider = keenableProvider()
    const { display } = resolveQuota(provider, undefined, false)
    expect(display.periodLabel).toBe("Hourly")
    expect(display.headline).toBe("Hourly quota pending")
  })
})

/** Slice 2.2 characterization: provider-specific quota captions. */
describe("quotaCaptionFor provider explanations", () => {
  it("explains unbudgeted Parallel differently when paired vs unpaired", () => {
    const provider = quotaProvider("parallel")
    const latest = snapshot("parallel")
    const unpairedDisplay = resolveQuota(provider, latest, false).display
    expect(quotaCaptionFor(provider, latest, unpairedDisplay, false)).toMatchObject({
      testId: "quota-explainer-parallel",
      text: "No API-key balance endpoint is available. Configure a local monthly USD budget to calculate remaining capacity.",
    })
    const pairedDisplay = resolveQuota(provider, latest, true).display
    expect(quotaCaptionFor(provider, latest, pairedDisplay, true)).toMatchObject({
      testId: "quota-explainer-parallel",
      text: "Balance will appear after first use.",
    })
  })

  it("explains Exa, Brave, and Keenable gaps separately", () => {
    const exa = quotaProvider("exa")
    const exaLatest = snapshot("exa")
    expect(
      quotaCaptionFor(exa, exaLatest, resolveQuota(exa, exaLatest, false).display, false)?.text
    ).toMatch(/monthly budget or Exa Admin/i)
    const brave = quotaProvider("brave")
    const braveLatest = snapshot("brave")
    expect(
      quotaCaptionFor(brave, braveLatest, resolveQuota(brave, braveLatest, false).display, false)?.text
    ).toMatch(/unbounded limit/i)
    const keenable = keenableProvider()
    const keenableLatest = snapshot("keenable")
    expect(
      quotaCaptionFor(keenable, keenableLatest, resolveQuota(keenable, keenableLatest, false).display, false)?.text
    ).toMatch(/shared per-IP pool/i)
  })

  it("stays silent once a snapshot or percentage exists", () => {
    const provider = quotaProvider("parallel")
    const seeded = snapshot("parallel", {
      remaining: "3.75",
      remainingPercent: "75",
      limit: "5.00",
    })
    expect(
      quotaCaptionFor(provider, seeded, resolveQuota(provider, seeded, false).display, false)
    ).toBeNull()
    const unknown = quotaProvider("tavily")
    expect(
      quotaCaptionFor(unknown, snapshot("tavily"), resolveQuota(unknown, snapshot("tavily"), false).display, false)
    ).toBeNull()
  })
})
