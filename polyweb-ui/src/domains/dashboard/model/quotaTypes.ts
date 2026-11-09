import type { UnitKind } from "@/shared/api/units";

export type QuotaConfidence = "authoritative" | "observed" | "estimated";

export interface DashboardQuota {
  provider: string;
  remaining: string | null;
  remainingPercent: string | null;
  limit: string | null;
  observed_at: string;
  source: QuotaConfidence;
  unitKind: UnitKind | null;
  displayUnit: string | null;
  resetAt: string | null;
  window: string | null;
}
