/**
 * Dashboard slice — verbatim extract from ../backendFixtures.ts (step 1).
 */

export interface WireDashboardUsageTotal {
  provider: string
  operation: string
  total_units: string
  event_count: number
  unit_kind?: string | null
}

export interface WireDashboardRecentUsage {
  provider: string
  operation: string
  units: string
  observed_at: string
  latency_ms: number | null
  status: string
  unit_kind?: string | null
  display_unit?: string | null
}

export interface WireDashboardQuota {
  provider: string
  source: "authoritative" | "observed" | "estimated"
  observed_at: string
  remaining: string | null
  remaining_percent?: string | null
  /** Decimal-as-string verbatim; null means no hard limit (e.g. You.com ESTIMATED). */
  limit: string | null
  reset_at: string | null
  unit_kind?: string | null
  display_unit?: string | null
}

export interface WireDashboard {
  notice: string
  usage_totals: WireDashboardUsageTotal[]
  recent_usage: WireDashboardRecentUsage[]
  latest_quota: WireDashboardQuota[]
  latest_health: Array<{ provider: string; status: string; checked_at: string }>
  generated_at: string
}

export function dashboardFixture(
  overrides: Partial<WireDashboard> = {}
): WireDashboard {
  return {
    notice: "Usage, quota, and health shown here are local-observed only.",
    usage_totals: [
      {
        provider: "tavily",
        operation: "search",
        total_units: "3.5",
        event_count: 4,
        unit_kind: "CREDIT",
      },
      {
        provider: "brave",
        operation: "search",
        total_units: "12",
        event_count: 12,
        unit_kind: "REQUEST",
      },
    ],
    recent_usage: [
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
        operation: "fetch",
        units: "0.001",
        observed_at: "2026-09-06T09:55:00Z",
        latency_ms: null,
        status: "failure",
        unit_kind: "REQUEST",
        display_unit: "requests",
      },
    ],
    latest_quota: [],
    latest_health: [
      { provider: "tavily", status: "healthy", checked_at: "2026-09-06T10:00:00Z" },
    ],
    generated_at: "2026-09-06T10:01:00Z",
    ...overrides,
  }
}
