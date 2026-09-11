import type { UnitKind } from "@/shared/api/units";

export interface UsageEvent {
  id: string;
  timestamp: string;
  operation: "search" | "fetch";
  queryOrUrl: string;
  providerId: string;
  providerName: string;
  latencyMs: number | null;
  costCredits: number;
  status: "success" | "error" | "fallback_recovered";
  routeReason: string;
  fallbackChain: string[];
  unitKind: UnitKind | null;
  displayUnit: string | null;
}

export interface UsageTotal {
  provider: string;
  operation: string;
  total_units: string;
  unitKind: UnitKind | null;
  eventCount: number;
}
