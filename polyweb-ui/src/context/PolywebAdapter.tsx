import React, { useEffect, useMemo } from "react";
import { PolywebContext } from "./context";
import { useNotifications } from "@/shared/notifications/useNotifications";
import { useProviders } from "@/domains/providers/state/useProviders";
import { useRouting } from "@/domains/routing/state/useRouting";
import { useDashboard } from "@/domains/dashboard/state/useDashboard";
import { overlayDashboardQuotas } from "@/app/selectors/dashboardOverlay";

/**
 * Legacy adapter: preserves the usePolyweb interface over focused domain
 * state. Behavior contracts (ordering, rollback, refresh, loading/error
 * semantics) live in the domain modules; this only composes them.
 */
export const PolywebAdapter: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { toasts, showToast, dismissToast } = useNotifications();
  const providers = useProviders();
  const routing = useRouting();
  const dashboard = useDashboard();
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
  const value = useMemo(
    () => ({
      ...providers,
      ...routingState,
      ...dashboard,
      providers: providersWithQuota,
      toasts,
      showToast,
      dismissToast,
    }),
    [providers, routingState, dashboard, providersWithQuota, toasts, showToast, dismissToast],
  );

  return <PolywebContext.Provider value={value}>{children}</PolywebContext.Provider>;
};
