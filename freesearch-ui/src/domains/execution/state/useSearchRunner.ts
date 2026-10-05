import { useCallback } from "react";
import { apiService } from "@/services/api/freesearchApi";
import { errorMessage } from "@/shared/api/http";
import type { ToastNotification } from "@/shared/notifications/context";
import type { BackendSearchRequest } from "@/domains/execution/api/wire";
import type { SearchRequest, SearchResponse } from "@/domains/execution";
import type { UsageEvent } from "@/domains/dashboard";
import { mapSearchResponse } from "@/services/api/mappers";
import { clampLimit, createTimeoutSignal, makeSearchEvent } from "@/domains/execution";
import { toBackendId } from "@/domains/providers";
import type { ProviderConfig } from "@/domains/providers/model/types";
import type { RoutingPreset } from "@/domains/routing/model/types";
import { getEligibleProviders } from "@/domains/routing/model/routingPolicy";
import { pickFallbackSearchProvider } from "@/domains/execution/model/searchFallback";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import {
  clearSearch as clearSearchAction,
  searchFailed,
  searchFinished,
  searchStarted,
  searchSucceeded,
  selectActiveSearch,
  selectIsSearching,
  selectSearchError,
} from "@/store/playgroundSlice";

export type ShowToast = (message: string, type?: ToastNotification["type"]) => void;

interface SearchRunnerDeps {
  showToast: ShowToast;
  fallbackEnabled: boolean;
  catalogNameOf: (id: string) => string | undefined;
  refreshDashboard: () => Promise<void>;
  prependUsageEvent: (event: UsageEvent) => void;
  providers: ProviderConfig[];
  routingPreset: RoutingPreset;
}

/**
 * Search API orchestration: request mapping, timeout budget, fallback walk,
 * toasts, usage events, and dashboard refresh stay here. Execution state itself
 * lives in the playground slice so it survives navigation and reload.
 */
export function useSearchRunner({
  showToast,
  fallbackEnabled,
  catalogNameOf,
  refreshDashboard,
  prependUsageEvent,
  providers,
  routingPreset,
}: SearchRunnerDeps) {
  const dispatch = useAppDispatch();
  const activeSearch = useAppSelector(selectActiveSearch);
  const isSearching = useAppSelector(selectIsSearching);
  const searchError = useAppSelector(selectSearchError);

  const runSearch = useCallback(
    async (request: SearchRequest): Promise<SearchResponse | null> => {
      dispatch(searchStarted());
      const startedAt = performance.now();
      const requestedProviderIds = request.providerIds ?? [];

      const isFanout = Boolean(request.fanout);
      const attempt = async (providerIds: string[]) => {
        const body: BackendSearchRequest = {
          query: request.query.trim(),
          limit: clampLimit(request.maxResults),
          language: null,
          country_code: null,
          domains: [],
          routing: {
            mode: isFanout ? "fanout" : providerIds.length > 0 ? "require" : "auto",
            providers: providerIds.map(toBackendId),
            allow_fallback: fallbackEnabled,
          },
          ...(isFanout ? { fanout: true } : {}),
        };
        // Fresh timeout budget per attempt: a hung primary must not steal
        // the fallback's time.
        const wire = await apiService.search(body, createTimeoutSignal(request.timeoutMs));
        return mapSearchResponse(wire, {
          wallClockMs: Math.round(performance.now() - startedAt),
          catalogNameOf,
        });
      };

      const succeed = (response: SearchResponse) => {
        dispatch(searchSucceeded(response));
        prependUsageEvent(makeSearchEvent(response));
        void refreshDashboard();
        return response;
      };

      const fail = (error: unknown) => {
        const message = errorMessage(error, "Search failed");
        dispatch(searchFailed(message));
        showToast(message, "error");
        return null;
      };

      try {
        return succeed(await attempt(requestedProviderIds));
      } catch (primaryError) {
        // Fanout searches handle partial failures on the server via ranked fusion;
        // a total fanout failure must surface directly without falling back to an
        // arbitrary single provider.
        if (isFanout || !fallbackEnabled) return fail(primaryError);
        // Auto mode pins nothing, so the arbitrated pick is unknown — assume
        // the backend tried the head of the same policy ordering and walk to
        // the next provider, never retrying the failed one.
        const triedUiIds =
          requestedProviderIds.length > 0
            ? requestedProviderIds
            : getEligibleProviders(providers, "search", routingPreset)
                .slice(0, 1)
                .map((provider) => provider.id);
        const fallback = pickFallbackSearchProvider(providers, routingPreset, triedUiIds);
        if (!fallback) return fail(primaryError);
        try {
          return succeed(await attempt([fallback.id]));
        } catch (fallbackError) {
          return fail(fallbackError);
        }
      } finally {
        dispatch(searchFinished());
      }
    },
    [dispatch, fallbackEnabled, refreshDashboard, showToast, catalogNameOf, prependUsageEvent, providers, routingPreset],
  );

  const clearSearch = useCallback(() => {
    dispatch(clearSearchAction());
  }, [dispatch]);

  return { activeSearch, isSearching, searchError, runSearch, clearSearch };
}
