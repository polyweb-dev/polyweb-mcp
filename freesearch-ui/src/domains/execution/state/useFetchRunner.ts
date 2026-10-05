import { useCallback } from "react";
import { apiService } from "@/services/api/freesearchApi";
import { errorMessage } from "@/shared/api/http";
import type { ToastNotification } from "@/shared/notifications/context";
import type { FetchRequest, FetchResponse } from "@/domains/execution";
import type { UsageEvent } from "@/domains/dashboard";
import { mapFetchResponse } from "@/services/api/mappers";
import { createTimeoutSignal, makeFetchEvent } from "@/domains/execution";
import { toBackendId } from "@/domains/providers";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import {
  clearFetch as clearFetchAction,
  fetchFailed,
  fetchFinished,
  fetchStarted,
  fetchSucceeded,
  selectActiveFetch,
  selectFetchError,
  selectIsFetching,
} from "@/store/playgroundSlice";

export type ShowToast = (message: string, type?: ToastNotification["type"]) => void;

interface FetchRunnerDeps {
  showToast: ShowToast;
  fallbackEnabled: boolean;
  refreshDashboard: () => Promise<void>;
  prependUsageEvent: (event: UsageEvent) => void;
}

/**
 * Fetch API orchestration: request mapping, timeout, toasts, usage events, and
 * dashboard refresh stay here; the fetched document and its status live in the
 * playground slice so they survive navigation and reload.
 */
export function useFetchRunner({
  showToast,
  fallbackEnabled,
  refreshDashboard,
  prependUsageEvent,
}: FetchRunnerDeps) {
  const dispatch = useAppDispatch();
  const activeFetch = useAppSelector(selectActiveFetch);
  const isFetching = useAppSelector(selectIsFetching);
  const fetchError = useAppSelector(selectFetchError);

  const runFetch = useCallback(
    async (request: FetchRequest): Promise<FetchResponse | null> => {
      // Starting a fetch also drops the previous document (fetchStarted).
      dispatch(fetchStarted());
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
        dispatch(fetchSucceeded(response));
        prependUsageEvent(makeFetchEvent(response));
        void refreshDashboard();
        return response;
      } catch (error) {
        const message = errorMessage(error, "Document fetch failed");
        dispatch(fetchFailed(message));
        showToast(message, "error");
        return null;
      } finally {
        dispatch(fetchFinished());
      }
    },
    [dispatch, fallbackEnabled, refreshDashboard, showToast, prependUsageEvent],
  );

  const clearFetch = useCallback(() => {
    dispatch(clearFetchAction());
  }, [dispatch]);

  return { activeFetch, isFetching, fetchError, runFetch, clearFetch };
}
