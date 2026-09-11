import React, { useCallback } from "react";
import type { ToastNotification } from "@/shared/notifications/context";
import type { UsageEvent } from "@/domains/dashboard";
import type { ProviderConfig } from "@/domains/providers/model/types";
import type { RoutingPreset } from "@/domains/routing/model/types";
import { ExecutionContext } from "./context";
import { useSearchRunner } from "./useSearchRunner";
import { useFetchRunner } from "./useFetchRunner";

export type ShowToast = (message: string, type?: ToastNotification["type"]) => void;

export const ExecutionProvider: React.FC<{
  showToast: ShowToast;
  fallbackEnabled: boolean;
  catalogNameOf: (id: string) => string | undefined;
  refreshDashboard: () => Promise<void>;
  prependUsageEvent: (event: UsageEvent) => void;
  providers: ProviderConfig[];
  routingPreset: RoutingPreset;
  children: React.ReactNode;
}> = ({ showToast, fallbackEnabled, catalogNameOf, refreshDashboard, prependUsageEvent, providers, routingPreset, children }) => {
  const { activeSearch, isSearching, searchError, runSearch, clearSearch } = useSearchRunner({
    showToast,
    fallbackEnabled,
    catalogNameOf,
    refreshDashboard,
    prependUsageEvent,
    providers,
    routingPreset,
  });
  const { activeFetch, isFetching, fetchError, runFetch, clearFetch } = useFetchRunner({
    showToast,
    fallbackEnabled,
    refreshDashboard,
    prependUsageEvent,
  });

  const clearActiveResults = useCallback(() => {
    clearSearch();
    clearFetch();
  }, [clearSearch, clearFetch]);

  const value = React.useMemo(
    () => ({
      activeSearch,
      activeFetch,
      isSearching,
      isFetching,
      searchError,
      fetchError,
      runSearch,
      runFetch,
      clearActiveResults,
    }),
    [
      activeSearch,
      activeFetch,
      isSearching,
      isFetching,
      searchError,
      fetchError,
      runSearch,
      runFetch,
      clearActiveResults,
    ],
  );

  return <ExecutionContext.Provider value={value}>{children}</ExecutionContext.Provider>;
};
