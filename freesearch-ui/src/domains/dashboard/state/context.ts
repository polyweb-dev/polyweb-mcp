import { createContext } from "react";
import type {
  CRDUsageTotal,
  DashboardQuota,
  ProviderLimits,
  UsageEvent,
  UsageTotal,
} from "@/domains/dashboard";

export interface DashboardValue {
  usageEvents: UsageEvent[];
  usageLoading: boolean;
  usageError: string | null;
  usageTotals: UsageTotal[];
  dashboardQuotas: DashboardQuota[];
  /** Decoded credit-unit limit state, one entry per provider rail. */
  providerLimits: ProviderLimits[];
  /** Exact credit-unit use totals from the dashboard payload. */
  crdUsageTotals: CRDUsageTotal[];
  quotaAvailable: boolean;
  dashboardNotice: string | null;
  /** Role capability flags from the composition. */
  canReadControls: boolean;
  canEditControls: boolean;
  refreshDashboard: () => Promise<void>;
}

export const DashboardContext = createContext<DashboardValue | undefined>(undefined);
