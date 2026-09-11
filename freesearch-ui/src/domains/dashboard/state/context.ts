import { createContext } from "react";
import type { DashboardQuota, UsageEvent, UsageTotal } from "@/domains/dashboard";

export interface DashboardValue {
  usageEvents: UsageEvent[];
  usageLoading: boolean;
  usageError: string | null;
  usageTotals: UsageTotal[];
  dashboardQuotas: DashboardQuota[];
  quotaAvailable: boolean;
  dashboardNotice: string | null;
  refreshDashboard: () => Promise<void>;
  prependUsageEvent: (event: UsageEvent) => void;
}

export const DashboardContext = createContext<DashboardValue | undefined>(undefined);
