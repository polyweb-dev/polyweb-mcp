import React, { useCallback } from "react";
import type { ToastNotification } from "@/shared/notifications/context";
import type { UsageEvent } from "@/domains/dashboard";
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
  children: React.ReactNode;
}> = ({ showToast, fallbackEnabled, catalogNameOf, refreshDashboard, prependUsageEvent, children }) => {
  const { activeSearch, isSearching, searchError, runSearch, clearSearch } = useSearchRunner({
    showToast,
    fallbackEnabled,
    catalogNameOf,
    refreshDashboard,
    prependUsageEvent,
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
