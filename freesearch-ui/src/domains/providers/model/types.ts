import type { UnitKind } from "@/shared/api/units";
// Explicit acyclic type-only edge: providers references the dashboard-owned
// QuotaConfidence (dashboard never imports providers types). See plan rule 3.
import type { QuotaConfidence } from "@/domains/dashboard/model/quotaTypes";

export type Capability =
  | "search"
  | "fetch"
  | "extract"
  | "neural_search"
  | "live_crawl"
  | "keyless_tier";

export type ProviderHealthStatus =
  | "healthy"
  | "degraded"
  | "rate_limited"
  | "circuit_broken"
  | "offline";

export type CircuitBreakerStatus = "closed" | "open" | "half_open";

export type KeySource = "encrypted_db" | "none";

export interface ProviderQuota {
  used: number | null;
  limit: string | null;
  unit: string;
  confidence: QuotaConfidence;
  resetPeriod: string | null;
  nextReset: string | null;
  /** Dashboard overlay: exact decimal string from the backend, never float-cast for display. */
  remaining: string | null;
  /** Canonical backend-derived 0..100 remaining percentage, when available. */
  remainingPercent: string | null;
  unitKind: UnitKind | null;
  displayUnit: string | null;
  observedAt: string | null;
  /** Optional rolling window label, used by keyless rate-limit snapshots. */
  window: string | null;
}

export interface ProviderConfig {
  id: string;
  name: string;
  description: string;
  baseUrl: string;
  isCustom: boolean;
  capabilities: Capability[];
  globalEnabled: boolean;
  searchEnabled: boolean;
  fetchEnabled: boolean;
  priority: number;
  healthStatus: ProviderHealthStatus;
  circuitBreaker: CircuitBreakerStatus;
  consecutiveFailures: number;
  latencyP95Ms: number | null;
  hasKey: boolean;
  keyMasked: string;
  keyVaultStatus: "configured" | "missing" | "keyless_public";
  keySource?: KeySource;
  authHeaderName?: string;
  quota: ProviderQuota;
}
