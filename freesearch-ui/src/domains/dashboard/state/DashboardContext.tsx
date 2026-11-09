import React, { useCallback, useState } from "react";
import { apiService } from "@/services/api/freesearchApi";
import { errorMessage } from "@/shared/api/http";
import type { ToastNotification } from "@/shared/notifications/context";
import type { UsdUsageTotal, DashboardQuota, ProviderLimits, UsageEvent, UsageTotal } from "@/domains/dashboard";
import {
  mapDashboardQuotas,
  mapDashboardTotals,
  mapDashboardUsage,
} from "@/services/api/mappers";
import { decodeUsdUsageTotals, decodeProviderLimits } from "../api/limitsWire";

export type ShowToast = (message: string, type?: ToastNotification["type"]) => void;

import { DashboardContext } from "./context";

export const DashboardProvider: React.FC<{
  showToast: ShowToast;
  catalogNameOf: (id: string) => string | undefined;
  canReadControls: boolean;
  canEditControls: boolean;
  children: React.ReactNode;
}> = ({ showToast, catalogNameOf, canReadControls, canEditControls, children }) => {
  const [usageEvents, setUsageEvents] = useState<UsageEvent[]>([]);
  const [usageLoading, setUsageLoading] = useState(true);
  const [usageError, setUsageError] = useState<string | null>(null);
  const [usageTotals, setUsageTotals] = useState<UsageTotal[]>([]);
  const [dashboardQuotas, setDashboardQuotas] = useState<DashboardQuota[]>([]);
  const [providerLimits, setProviderLimits] = useState<ProviderLimits[]>([]);
  const [usdUsageTotals, setUsdUsageTotals] = useState<UsdUsageTotal[]>([]);
  const [dashboardNotice, setDashboardNotice] = useState<string | null>(null);
  const quotaAvailable = dashboardQuotas.length > 0;
  // Only the newest dashboard request may write state, so a slow older
  // response can never restore old funds or old priced use.
  const requestGeneration = React.useRef(0);

  const refreshDashboard = useCallback(async () => {
    if (!canReadControls) {
      // A role without control-read access keeps an empty telemetry state and a
      // clear busy flag.
      setUsageEvents([]);
      setUsageTotals([]);
      setDashboardQuotas([]);
      setProviderLimits([]);
      setUsdUsageTotals([]);
      setDashboardNotice(null);
      setUsageError(null);
      setUsageLoading(false);
      return;
    }
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
      setUsdUsageTotals(decodeUsdUsageTotals(dashboard.spend_totals));
      setDashboardNotice(dashboard.notice);
    } catch (error) {
      if (generation !== requestGeneration.current) return;
      const message = errorMessage(error, "Unable to load usage telemetry");
      setUsageEvents([]);
      setUsageTotals([]);
      setDashboardQuotas([]);
      setProviderLimits([]);
      setUsdUsageTotals([]);
      setUsageError(message);
      showToast(message, "error");
    } finally {
      if (generation === requestGeneration.current) setUsageLoading(false);
    }
  }, [canReadControls, showToast, catalogNameOf]);

  const value = React.useMemo(
    () => ({
      usageEvents,
      usageLoading,
      usageError,
      usageTotals,
      dashboardQuotas,
      providerLimits,
      usdUsageTotals,
      quotaAvailable,
      dashboardNotice,
      canReadControls,
      canEditControls,
      refreshDashboard,
    }),
    [
      usageEvents,
      usageLoading,
      usageError,
      usageTotals,
      dashboardQuotas,
      providerLimits,
      usdUsageTotals,
      quotaAvailable,
      dashboardNotice,
      canReadControls,
      canEditControls,
      refreshDashboard,
    ],
  );

  return <DashboardContext.Provider value={value}>{children}</DashboardContext.Provider>;
};
