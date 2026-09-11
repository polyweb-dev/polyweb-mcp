import { useCallback, useState } from "react";
import { apiService } from "@/services/api/freesearchApi";
import { errorMessage } from "@/shared/api/http";
import type { ToastNotification } from "@/shared/notifications/context";
import type { FetchRequest, FetchResponse } from "@/domains/execution";
import type { UsageEvent } from "@/domains/dashboard";
import { mapFetchResponse } from "@/services/api/mappers";
import { createTimeoutSignal, makeFetchEvent } from "@/domains/execution";
import { toBackendId } from "@/domains/providers";

export type ShowToast = (message: string, type?: ToastNotification["type"]) => void;

interface FetchRunnerDeps {
  showToast: ShowToast;
  fallbackEnabled: boolean;
  refreshDashboard: () => Promise<void>;
  prependUsageEvent: (event: UsageEvent) => void;
}

export function useFetchRunner({
  showToast,
  fallbackEnabled,
  refreshDashboard,
  prependUsageEvent,
}: FetchRunnerDeps) {
  const [activeFetch, setActiveFetch] = useState<FetchResponse | null>(null);
  const [isFetching, setIsFetching] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);

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

  const clearFetch = useCallback(() => {
    setActiveFetch(null);
    setFetchError(null);
  }, []);

  return { activeFetch, isFetching, fetchError, runFetch, clearFetch };
}
