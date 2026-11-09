import { useCallback } from "react";
import { apiService } from "@/services/api/polywebApi";
import { errorMessage } from "@/shared/api/http";
import type { BackendFetchRequest } from "@/domains/execution/api/wire";
import type { FetchRequest, FetchResponse } from "@/domains/execution/model/types";
import { mapFetchResponse } from "@/services/api/mappers";
import { withTimeout } from "@/domains/execution/model/requestUtils";
import { toBackendId } from "@/domains/providers";
import { useAppDispatch } from "@/store/hooks";
import {
  fetchFailed,
  fetchFinished,
  fetchStarted,
  fetchSucceeded,
} from "@/store/playgroundSlice";
import type { ShowToast } from "./projectExecutionContext";
import { useScopedRequest } from "./useScopedRequest";

interface FetchRunnerDeps {
  projectId: string;
  showToast: ShowToast;
}

/** Wire body of one project fetch: the server routes across the project bindings. */
export function fetchBody(projectId: string, request: FetchRequest): BackendFetchRequest {
  return {
    project_id: projectId,
    url: request.url.trim(),
    max_chars: null,
    routing: {
      mode: request.providerId ? "require" : "auto",
      providers: request.providerId ? [toBackendId(request.providerId)] : [],
      allow_fallback: true,
    },
  };
}

/**
 * Project fetch orchestration: request mapping, timeout, abort, and toasts.
 * The fetched document and its status live in the project playground slice.
 * Unmount or a project switch aborts the request, and a late result never
 * dispatches.
 */
export function useFetchRunner({ projectId, showToast }: FetchRunnerDeps) {
  const dispatch = useAppDispatch();
  const { begin, end } = useScopedRequest();

  return useCallback(
    async (request: FetchRequest): Promise<FetchResponse | null> => {
      const controller = begin();
      // Starting a fetch also drops the previous document (fetchStarted).
      dispatch(fetchStarted());
      const startedAt = performance.now();
      try {
        const wire = await apiService.fetchDoc(
          fetchBody(projectId, request),
          withTimeout(controller.signal, request.timeoutMs),
        );
        if (controller.signal.aborted) return null;
        const response = mapFetchResponse(wire, {
          wallClockMs: Math.round(performance.now() - startedAt),
        });
        dispatch(fetchSucceeded(response));
        return response;
      } catch (error) {
        if (controller.signal.aborted) return null;
        const message = errorMessage(error, "Document fetch failed");
        dispatch(fetchFailed(message));
        showToast(message, "error");
        return null;
      } finally {
        if (!controller.signal.aborted) dispatch(fetchFinished());
        end(controller);
      }
    },
    [begin, end, dispatch, projectId, showToast],
  );
}
