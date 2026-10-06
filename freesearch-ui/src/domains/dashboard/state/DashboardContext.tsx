import React, { useCallback, useState } from "react";
import { apiService } from "@/services/api/freesearchApi";
import { errorMessage } from "@/shared/api/http";
import type { ToastNotification } from "@/shared/notifications/context";
import type { CRDUsageTotal, DashboardQuota, ProviderLimits, UsageEvent, UsageTotal } from "@/domains/dashboard";
import {
  mapDashboardQuotas,
  mapDashboardTotals,
  mapDashboardUsage,
} from "@/services/api/mappers";
import { decodeCRDUsageTotals, decodeProviderLimits } from "../api/limitsWire";

export type ShowToast = (message: string, type?: ToastNotification["type"]) => void;

import { DashboardContext } from "./context";

export const DashboardProvider: React.FC<{
  showToast: ShowToast;
  catalogNameOf: (id: string) => string | undefined;
  children: React.ReactNode;
}> = ({ showToast, catalogNameOf, children }) => {
  const [usageEvents, setUsageEvents] = useState<UsageEvent[]>([]);
  const [usageLoading, setUsageLoading] = useState(true);
  const [usageError, setUsageError] = useState<string | null>(null);
  const [usageTotals, setUsageTotals] = useState<UsageTotal[]>([]);
  const [dashboardQuotas, setDashboardQuotas] = useState<DashboardQuota[]>([]);
  const [providerLimits, setProviderLimits] = useState<ProviderLimits[]>([]);
  const [crdUsageTotals, setCrdUsageTotals] = useState<CRDUsageTotal[]>([]);
  const [dashboardNotice, setDashboardNotice] = useState<string | null>(null);
  const quotaAvailable = dashboardQuotas.length > 0;
  // Only the newest dashboard request may write state, so a slow older
  // response can never restore old funds or old priced use.
  const requestGeneration = React.useRef(0);

  const refreshDashboard = useCallback(async () => {
    requestGeneration.current += 1;
    const generation = requestGeneration.current;
    setUsageLoading(true);
    setUsageError(null);
    try {
      const dashboard = await apiService.getDashboard();
      if (generation !== requestGeneration.current) return;
      setUsageEvents(mapDashboardUsage(dashboard, catalogNameOf));
      setUsageTotals(mapDashboardTotals(dashboard));
      setDashboardQuotas(mapDashboardQuotas(dashboard));
      setProviderLimits(decodeProviderLimits(dashboard.provider_limits));
      setCrdUsageTotals(decodeCRDUsageTotals(dashboard.crd_usage_totals));
      setDashboardNotice(dashboard.notice);
    } catch (error) {
      if (generation !== requestGeneration.current) return;
      const message = errorMessage(error, "Unable to load usage telemetry");
      setUsageEvents([]);
      setUsageTotals([]);
      setDashboardQuotas([]);
      setProviderLimits([]);
      setCrdUsageTotals([]);
      setUsageError(message);
      showToast(message, "error");
    } finally {
      if (generation === requestGeneration.current) setUsageLoading(false);
    }
  }, [showToast, catalogNameOf]);

  const value = React.useMemo(
    () => ({
      usageEvents,
      usageLoading,
      usageError,
      usageTotals,
      dashboardQuotas,
      providerLimits,
      crdUsageTotals,
      quotaAvailable,
      dashboardNotice,
      refreshDashboard,
      prependUsageEvent: (event: UsageEvent) =>
        setUsageEvents((previous) => [event, ...previous]),
    }),
    [
      usageEvents,
      usageLoading,
      usageError,
      usageTotals,
      dashboardQuotas,
      providerLimits,
      crdUsageTotals,
      quotaAvailable,
      dashboardNotice,
      refreshDashboard,
    ],
  );

  return <DashboardContext.Provider value={value}>{children}</DashboardContext.Provider>;
};
