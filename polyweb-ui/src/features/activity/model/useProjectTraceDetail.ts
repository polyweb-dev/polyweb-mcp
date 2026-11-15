import { useCallback } from "react"
import { TRACE_NOT_RECORDED_MESSAGE, getProjectTrace, type TraceDetail } from "@/domains/activity"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import { failedDetail, type TraceLoadState } from "./useActivityController"

export const TRACE_READ_NOT_PERMITTED_MESSAGE =
  "You need permission to read this project's Activity to see these details."

/** Detail state of one trace, with a manual retry after a failed read. */
export interface ProjectTraceDetail extends TraceLoadState {
  retry: () => void
}

/** Which trace to read, and whether the caller may read project traces. */
export interface ProjectTraceRequest {
  projectId: string
  /** Trace of the call; null when the backend recorded none. */
  traceId: string | null
  canReadTraces: boolean
}

function unavailable(error: string): TraceLoadState {
  return { status: "missing", detail: null, error }
}

/**
 * One trace of the project, read through the project route only. A call
 * without a trace id, or a caller without `traces.read`, has nothing to read:
 * the state is `missing` with its own explanation, and no list or global read
 * looks for the trace. The read is keyed by `projectId:traceId`, so a late
 * answer for another trace never shows.
 */
export function useProjectTraceDetail({
  projectId,
  traceId,
  canReadTraces,
}: ProjectTraceRequest): ProjectTraceDetail {
  const load = useCallback(
    (signal: AbortSignal): Promise<TraceDetail> => getProjectTrace(projectId, traceId ?? "", signal),
    [projectId, traceId]
  )
  const resource = useScopedResource({
    scopeKey: `${projectId}:${traceId ?? ""}`,
    load,
    enabled: traceId !== null && canReadTraces,
  })
  const { reload } = resource
  const retry = useCallback(() => {
    void reload()
  }, [reload])

  if (traceId === null) return { ...unavailable(TRACE_NOT_RECORDED_MESSAGE), retry }
  if (!canReadTraces) return { ...unavailable(TRACE_READ_NOT_PERMITTED_MESSAGE), retry }
  if (resource.status === "ready") return { status: "ready", detail: resource.data, error: null, retry }
  if (resource.status === "error") return { ...failedDetail(resource.error), retry }
  return { status: "loading", detail: null, error: null, retry }
}
