import React, { useCallback, useState } from "react";
import { apiService } from "@/services/api/freesearchApi";
import { errorMessage } from "@/shared/api/http";
import type { ToastNotification } from "@/shared/notifications/context";
import type { DashboardQuota, UsageEvent, UsageTotal } from "@/domains/dashboard";
import {
  mapDashboardQuotas,
  mapDashboardTotals,
  mapDashboardUsage,
} from "@/services/api/mappers";

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
  const [dashboardNotice, setDashboardNotice] = useState<string | null>(null);
  const quotaAvailable = dashboardQuotas.length > 0;

  const refreshDashboard = useCallback(async () => {
    if (!canReadControls) {
      // A role without control-read access keeps an empty telemetry state and a
      // clear busy flag. This covers the startup read and the post-search read.
      setUsageEvents([]);
      setUsageTotals([]);
      setDashboardQuotas([]);
      setDashboardNotice(null);
      setUsageError(null);
      setUsageLoading(false);
      return;
    }
    setUsageLoading(true);
    setUsageError(null);
    try {
      const dashboard = await apiService.getDashboard();
      setUsageEvents(mapDashboardUsage(dashboard, catalogNameOf));
      setUsageTotals(mapDashboardTotals(dashboard));
      setDashboardQuotas(mapDashboardQuotas(dashboard));
      setDashboardNotice(dashboard.notice);
    } catch (error) {
      const message = errorMessage(error, "Unable to load usage telemetry");
      setUsageEvents([]);
      setUsageTotals([]);
      setDashboardQuotas([]);
      setUsageError(message);
      showToast(message, "error");
    } finally {
      setUsageLoading(false);
    }
  }, [canReadControls, showToast, catalogNameOf]);

  const value = React.useMemo(
    () => ({
      usageEvents,
      usageLoading,
      usageError,
      usageTotals,
      dashboardQuotas,
      quotaAvailable,
      dashboardNotice,
      canReadControls,
      canEditControls,
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
      quotaAvailable,
      dashboardNotice,
      canReadControls,
      canEditControls,
      refreshDashboard,
    ],
  );

  return <DashboardContext.Provider value={value}>{children}</DashboardContext.Provider>;
};
