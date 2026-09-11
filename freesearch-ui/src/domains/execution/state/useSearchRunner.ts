import { useCallback, useState } from "react";
import { apiService } from "@/services/api/freesearchApi";
import { errorMessage } from "@/shared/api/http";
import type { ToastNotification } from "@/shared/notifications/context";
import type { BackendSearchRequest } from "@/domains/execution/api/wire";
import type { SearchRequest, SearchResponse } from "@/domains/execution";
import type { UsageEvent } from "@/domains/dashboard";
import { mapSearchResponse } from "@/services/api/mappers";
import { clampLimit, createTimeoutSignal, makeSearchEvent } from "@/domains/execution";
import { toBackendId } from "@/domains/providers";

export type ShowToast = (message: string, type?: ToastNotification["type"]) => void;

interface SearchRunnerDeps {
  showToast: ShowToast;
  fallbackEnabled: boolean;
  catalogNameOf: (id: string) => string | undefined;
  refreshDashboard: () => Promise<void>;
  prependUsageEvent: (event: UsageEvent) => void;
}

export function useSearchRunner({
  showToast,
  fallbackEnabled,
  catalogNameOf,
  refreshDashboard,
  prependUsageEvent,
}: SearchRunnerDeps) {
  const [activeSearch, setActiveSearch] = useState<SearchResponse | null>(null);
  const [isSearching, setIsSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

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

  const clearSearch = useCallback(() => {
    setActiveSearch(null);
    setSearchError(null);
  }, []);

  return { activeSearch, isSearching, searchError, runSearch, clearSearch };
}
