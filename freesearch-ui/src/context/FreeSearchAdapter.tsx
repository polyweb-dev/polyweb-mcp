import React, { useEffect, useMemo } from "react";
import { FreeSearchContext } from "./context";
import { useNotifications } from "@/shared/notifications/useNotifications";
import { useProviders } from "@/domains/providers/state/useProviders";
import { useRouting } from "@/domains/routing/state/useRouting";
import { useDashboard } from "@/domains/dashboard/state/useDashboard";
import { useExecution } from "@/domains/execution/state/useExecution";
import { overlayDashboardQuotas } from "@/app/selectors/dashboardOverlay";

/**
 * Legacy adapter: preserves the useFreeSearch interface over focused domain
 * state. Behavior contracts (ordering, rollback, refresh, loading/error
 * semantics) live in the domain modules; this only composes them.
 */
export const FreeSearchAdapter: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { toasts, showToast, dismissToast } = useNotifications();
  const providers = useProviders();
  const routing = useRouting();
  const dashboard = useDashboard();
  const execution = useExecution();
  const { refreshProviders } = providers;
  const { refreshRouting } = routing;
  const { refreshDashboard } = dashboard;

  useEffect(() => {
    void refreshProviders();
    void refreshRouting();
    void refreshDashboard();
  }, [refreshProviders, refreshRouting, refreshDashboard]);

  const providersWithQuota = useMemo(
    () => overlayDashboardQuotas(providers.providers, dashboard.dashboardQuotas),
    [providers, dashboard],
  );

  const { refreshRouting: _refreshRouting, ...routingState } = routing;
  const { prependUsageEvent: _prependUsageEvent, ...dashboardState } = dashboard;
  const value = useMemo(
    () => ({
      ...providers,
      ...routingState,
      ...dashboardState,
      ...execution,
      providers: providersWithQuota,
      toasts,
      showToast,
      dismissToast,
    }),
    [providers, routingState, dashboardState, execution, providersWithQuota, toasts, showToast, dismissToast],
  );

  return <FreeSearchContext.Provider value={value}>{children}</FreeSearchContext.Provider>;
};
