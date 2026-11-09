/**
 * Canonical-dashboard slice — verbatim extract from ../backendFixtures.ts (step 1).
 */

import type {
  WireDashboardQuota,
  WireDashboardRecentUsage,
  WireDashboardUsageTotal,
} from "./dashboard"

/**
 * Canonical quota rows for the Final Review Plan (QUOTA.md §4 Option A).
 * Covers AUTHORITATIVE credits (Tavily), OBSERVED requests with reset_at
 * (Brave), ESTIMATED USD with limit null (You.com), and a null-kind legacy
 * row (Exa). Limit strings are verbatim Decimal-as-string: "100000.10" must
 * NOT become 100000.1 and "0.00000001" must NOT become 1e-8 (RF1).
 */
export function canonicalQuotasFixture(): WireDashboardQuota[] {
  return [
    {
      provider: "tavily",
      source: "authoritative",
      observed_at: "2026-09-06T18:00:00Z",
      remaining: "90000.05",
      remaining_percent: "90.00005",
      limit: "100000.10",
      reset_at: null,
      unit_kind: "CREDIT",
      display_unit: "credits",
    },
    {
      provider: "brave",
      source: "observed",
      observed_at: "2026-09-06T18:05:00Z",
      remaining: "950",
      remaining_percent: "95",
      limit: "1000",
      reset_at: "2026-10-01T00:00:00Z",
      unit_kind: "REQUEST",
      display_unit: "requests",
    },
    {
      provider: "you",
      source: "estimated",
      observed_at: "2026-09-06T18:10:00Z",
      remaining: "4.75",
      limit: null,
      reset_at: null,
      unit_kind: "USD",
      display_unit: "USD",
    },
    {
      provider: "exa",
      source: "estimated",
      observed_at: "2026-09-06T18:15:00Z",
      remaining: "0.00000005",
      limit: "0.00000001",
      reset_at: null,
      unit_kind: null,
      display_unit: null,
    },
  ]
}

/**
 * Triple-keyed usage totals: (provider, operation, unit_kind). The two Tavily
 * search rows share provider+operation but differ in unit_kind and must stay
 * separate; the Exa row omits unit_kind entirely (legacy null-kind).
 */
export function canonicalTotalsFixture(): WireDashboardUsageTotal[] {
  return [
    {
      provider: "tavily",
      operation: "search",
      total_units: "3.5",
      event_count: 4,
      unit_kind: "CREDIT",
    },
    {
      provider: "tavily",
      operation: "search",
      total_units: "0.007",
      event_count: 2,
      unit_kind: "USD",
    },
    {
      provider: "brave",
      operation: "search",
      total_units: "12",
      event_count: 12,
      unit_kind: "REQUEST",
    },
    {
      provider: "exa",
      operation: "search",
      total_units: "9",
      event_count: 9,
    },
  ]
}

/** Canonical recent usage with unit_kind/display_unit plus a legacy row. */
export function canonicalRecentUsageFixture(): WireDashboardRecentUsage[] {
  return [
    {
      provider: "tavily",
      operation: "search",
      units: "1",
      observed_at: "2026-09-06T10:00:00Z",
      latency_ms: 230,
      status: "success",
      unit_kind: "CREDIT",
      display_unit: "credits",
    },
    {
      provider: "brave",
      operation: "search",
      units: "1",
      observed_at: "2026-09-06T10:01:00Z",
      latency_ms: 120,
      status: "success",
      unit_kind: "REQUEST",
      display_unit: "requests",
    },
    {
      provider: "you",
      operation: "search",
      units: "0.005",
      observed_at: "2026-09-06T10:02:00Z",
      latency_ms: 150,
      status: "success",
      unit_kind: "USD",
      display_unit: "USD",
    },
    {
      provider: "exa",
      operation: "search",
      units: "2",
      observed_at: "2026-09-06T10:03:00Z",
      latency_ms: null,
      status: "success",
    },
  ]
}
