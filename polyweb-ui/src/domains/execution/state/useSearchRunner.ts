import { useCallback } from "react";
import { apiService } from "@/services/api/polywebApi";
import { errorMessage } from "@/shared/api/http";
import type { BackendSearchRequest } from "@/domains/execution/api/wire";
import type { SearchRequest, SearchResponse } from "@/domains/execution/model/types";
import { mapSearchResponse } from "@/services/api/mappers";
import { clampLimit, withTimeout } from "@/domains/execution/model/requestUtils";
import { toBackendId } from "@/domains/providers";
import { useAppDispatch } from "@/store/hooks";
import {
  searchFailed,
  searchFinished,
  searchStarted,
  searchSucceeded,
} from "@/store/playgroundSlice";
import type { ShowToast } from "./projectExecutionContext";
import { useScopedRequest } from "./useScopedRequest";

interface SearchRunnerDeps {
  projectId: string;
  showToast: ShowToast;
  catalogNameOf: (id: string) => string | undefined;
}

/** Wire body of one project search: the server routes across the project bindings. */
export function searchBody(projectId: string, request: SearchRequest): BackendSearchRequest {
  const providerIds = request.providerIds ?? [];
  const isFanout = Boolean(request.fanout);
  return {
    project_id: projectId,
    query: request.query.trim(),
    limit: clampLimit(request.maxResults),
    language: null,
    country_code: null,
    domains: [],
    routing: {
      mode: isFanout ? "fanout" : providerIds.length > 0 ? "require" : "auto",
      providers: providerIds.map(toBackendId),
      allow_fallback: true,
    },
    ...(isFanout ? { fanout: true } : {}),
  };
}

/**
 * Project search orchestration: request mapping, timeout budget, abort, and
 * toasts. Every body carries the URL project and travels on the human session;
 * the server owns provider fallback, so a failure (a Tavily 402 included)
 * shows the backend message once and is never retried here. Unmount or a
 * project switch aborts the request, and a late result never dispatches.
 */
export function useSearchRunner({ projectId, showToast, catalogNameOf }: SearchRunnerDeps) {
  const dispatch = useAppDispatch();
  const { begin, end } = useScopedRequest();

  return useCallback(
    async (request: SearchRequest): Promise<SearchResponse | null> => {
      const controller = begin();
      dispatch(searchStarted());
      const startedAt = performance.now();
      try {
        const wire = await apiService.search(
          searchBody(projectId, request),
          withTimeout(controller.signal, request.timeoutMs),
        );
        if (controller.signal.aborted) return null;
        const response = mapSearchResponse(wire, {
          wallClockMs: Math.round(performance.now() - startedAt),
          catalogNameOf,
        });
        dispatch(searchSucceeded(response));
        return response;
      } catch (error) {
        if (controller.signal.aborted) return null;
        const message = errorMessage(error, "Search failed");
        dispatch(searchFailed(message));
        showToast(message, "error");
        return null;
      } finally {
        if (!controller.signal.aborted) dispatch(searchFinished());
        end(controller);
      }
    },
    [begin, end, dispatch, projectId, showToast, catalogNameOf],
  );
}
