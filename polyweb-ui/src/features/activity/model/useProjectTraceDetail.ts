import { useCallback } from "react"
import {
  TRACE_NOT_RECORDED_MESSAGE,
  TRACE_NOT_SAVED_MESSAGE,
  getProjectTrace,
  type TraceDetail,
} from "@/domains/activity"
import type { TraceUnavailableReason } from "@/domains/execution"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import { failedDetail } from "./useActivityController"

export const TRACE_READ_NOT_PERMITTED_MESSAGE =
  "You need permission to read this project's Activity to see these details."

const UNAVAILABLE_MESSAGES: Record<TraceUnavailableReason, string> = {
  not_recorded: TRACE_NOT_RECORDED_MESSAGE,
  not_saved: TRACE_NOT_SAVED_MESSAGE,
}

/** Detail state of one trace, with a manual retry after a failed read. */
export interface ProjectTraceDetail {
  status: "loading" | "ready" | "error" | "missing"
  detail: TraceDetail | null
  error: string | null
  retry: () => void
}

/** Which trace to read (or why there is none), and whether the caller may read traces. */
export interface ProjectTraceRequest {
  projectId: string
  traceId: string | null
  /** Why `traceId` is null; ignored when a trace id is present. */
  reason?: TraceUnavailableReason
  canReadTraces: boolean
}

function unavailable(error: string, retry: () => void): ProjectTraceDetail {
  return { status: "missing", detail: null, error, retry }
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
  reason = "not_recorded",
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

  if (traceId === null) return unavailable(UNAVAILABLE_MESSAGES[reason], retry)
  if (!canReadTraces) return unavailable(TRACE_READ_NOT_PERMITTED_MESSAGE, retry)
  if (resource.status === "ready") return { status: "ready", detail: resource.data, error: null, retry }
  if (resource.status === "error") {
    const failed = failedDetail(resource.error)
    return { status: failed.status === "missing" ? "missing" : "error", detail: null, error: failed.error, retry }
  }
  return { status: "loading", detail: null, error: null, retry }
}
