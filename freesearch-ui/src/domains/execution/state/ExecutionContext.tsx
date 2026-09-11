import React, { useCallback, useState } from "react";
import { apiService } from "@/services/api/freesearchApi";
import { errorMessage } from "@/shared/api/http";
import type { ToastNotification } from "@/shared/notifications/context";
import type { BackendSearchRequest } from "@/domains/execution/api/wire";
import type { FetchRequest, FetchResponse, SearchRequest, SearchResponse } from "@/domains/execution";
import type { UsageEvent } from "@/domains/dashboard";
import { mapFetchResponse, mapSearchResponse } from "@/services/api/mappers";
import {
  clampLimit,
  createTimeoutSignal,
  makeFetchEvent,
  makeSearchEvent,
} from "@/domains/execution";
import { toBackendId } from "@/domains/providers";

export type ShowToast = (message: string, type?: ToastNotification["type"]) => void;

import { ExecutionContext } from "./context";


export const ExecutionProvider: React.FC<{
  showToast: ShowToast;
  fallbackEnabled: boolean;
  catalogNameOf: (id: string) => string | undefined;
  refreshDashboard: () => Promise<void>;
  prependUsageEvent: (event: UsageEvent) => void;
  children: React.ReactNode;
}> = ({ showToast, fallbackEnabled, catalogNameOf, refreshDashboard, prependUsageEvent, children }) => {
  const [activeSearch, setActiveSearch] = useState<SearchResponse | null>(null);
  const [activeFetch, setActiveFetch] = useState<FetchResponse | null>(null);
  const [isSearching, setIsSearching] = useState(false);
  const [isFetching, setIsFetching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);

  const runSearch = useCallback(
    async (request: SearchRequest): Promise<SearchResponse | null> => {
      setIsSearching(true);
      setSearchError(null);
      const startedAt = performance.now();
      const providerIds = request.providerIds ?? [];
      const body: BackendSearchRequest = {
        query: request.query.trim(),
        limit: clampLimit(request.maxResults),
        language: null,
        country_code: null,
        domains: [],
        routing: {
          mode: providerIds.length > 0 ? "require" : "auto",
          providers: providerIds.map(toBackendId),
          allow_fallback: fallbackEnabled,
        },
      };

      try {
        const wire = await apiService.search(body, createTimeoutSignal(request.timeoutMs));
        const response = mapSearchResponse(wire, {
          wallClockMs: Math.round(performance.now() - startedAt),
          catalogNameOf,
        });
        setActiveSearch(response);
        prependUsageEvent(makeSearchEvent(response));
        void refreshDashboard();
        return response;
      } catch (error) {
        const message = errorMessage(error, "Search failed");
        setSearchError(message);
        showToast(message, "error");
        return null;
      } finally {
        setIsSearching(false);
      }
    },
    [fallbackEnabled, refreshDashboard, showToast, catalogNameOf, prependUsageEvent],
  );

  const runFetch = useCallback(
    async (request: FetchRequest): Promise<FetchResponse | null> => {
      setIsFetching(true);
      setFetchError(null);
      setActiveFetch(null);
      const startedAt = performance.now();
      const providerIds = request.providerId ? [toBackendId(request.providerId)] : [];
      const body = {
        url: request.url.trim(),
        max_chars: null,
        routing: {
          mode: request.providerId ? "require" : "auto",
          providers: providerIds,
          allow_fallback: fallbackEnabled,
        },
      } as const;

      try {
        const wire = await apiService.fetchDoc(body, createTimeoutSignal(request.timeoutMs));
        const response = mapFetchResponse(wire, {
          wallClockMs: Math.round(performance.now() - startedAt),
        });
        setActiveFetch(response);
        prependUsageEvent(makeFetchEvent(response));
        void refreshDashboard();
        return response;
      } catch (error) {
        const message = errorMessage(error, "Document fetch failed");
        setFetchError(message);
        showToast(message, "error");
        return null;
      } finally {
        setIsFetching(false);
      }
    },
    [fallbackEnabled, refreshDashboard, showToast, prependUsageEvent],
  );

  const clearActiveResults = useCallback(() => {
    setActiveSearch(null);
    setActiveFetch(null);
    setSearchError(null);
    setFetchError(null);
  }, []);

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

