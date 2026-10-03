import { useCallback, useEffect, useState } from "react"
import {
  mapTraceDetail,
  mapTraceList,
  type TraceDetail,
  type TraceOperation,
  type TraceSummary,
} from "@/domains/activity"
import { errorMessage, isAbortOrTimeout } from "@/shared/api/http"
import { apiService } from "@/services/api/freesearchApi"

/** Activity list filter: everything, or one provider-querying operation. */
export type ActivityFilter = "all" | TraceOperation

export type LoadStatus = "loading" | "ready" | "error"
export type DetailStatus = "idle" | LoadStatus

export interface ActivityController {
  filter: ActivityFilter
  setFilter: (filter: ActivityFilter) => void
  summaries: TraceSummary[]
  listStatus: LoadStatus
  listError: string | null
  refresh: () => void
  selectedTraceId: string | null
  detail: TraceDetail | null
  detailStatus: DetailStatus
  detailError: string | null
  openTrace: (traceId: string) => void
  closeTrace: () => void
  retryDetail: () => void
}

const LIST_LIMIT = 50

/**
 * Activity list/detail coordination. The list loads on mount and whenever the
 * filter changes; detail loads lazily on selection. Every request is
 * cancellable, so a fast filter change or a closed dialog cannot let a stale
 * response overwrite current state.
 */
export function useActivityController(): ActivityController {
  const [filter, setFilter] = useState<ActivityFilter>("all")
  const [summaries, setSummaries] = useState<TraceSummary[]>([])
  const [listStatus, setListStatus] = useState<LoadStatus>("loading")
  const [listError, setListError] = useState<string | null>(null)
  const [reloadToken, setReloadToken] = useState(0)
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null)
  const [detail, setDetail] = useState<TraceDetail | null>(null)
  const [detailStatus, setDetailStatus] = useState<DetailStatus>("idle")
  const [detailError, setDetailError] = useState<string | null>(null)
  const [detailToken, setDetailToken] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    const load = async () => {
      setListStatus("loading")
      setListError(null)
      try {
        const payload = await apiService.listTraces(
          {
            limit: LIST_LIMIT,
            ...(filter === "all" ? {} : { operation: filter }),
          },
          controller.signal
        )
        // Abort semantics belong to this controller, not to the transport: a
        // client that resolves after an abort (stub, custom transport, or a
        // resolve-then-abort race) must not publish a stale list.
        if (controller.signal.aborted) return
        setSummaries(mapTraceList(payload))
        setListStatus("ready")
      } catch (error) {
        if (controller.signal.aborted || isAbortOrTimeout(error)) return
        setListError(errorMessage(error, "Traces unavailable"))
        setListStatus("error")
      }
    }
    void load()
    return () => controller.abort()
  }, [filter, reloadToken])

  useEffect(() => {
    if (selectedTraceId === null) return
    const controller = new AbortController()
    const load = async () => {
      setDetailStatus("loading")
      setDetailError(null)
      try {
        const payload = await apiService.getTrace(selectedTraceId, controller.signal)
        // Keeps the controller's contract ("a closed dialog cannot let a stale
        // response overwrite current state") true even for a client that
        // resolves instead of rejecting after abort.
        if (controller.signal.aborted) return
        setDetail(mapTraceDetail(payload))
        setDetailStatus("ready")
      } catch (error) {
        if (controller.signal.aborted || isAbortOrTimeout(error)) return
        setDetail(null)
        setDetailError(errorMessage(error, "Trace detail unavailable"))
        setDetailStatus("error")
      }
    }
    void load()
    return () => controller.abort()
  }, [selectedTraceId, detailToken])

  const refresh = useCallback(() => setReloadToken((token) => token + 1), [])

  const openTrace = useCallback((traceId: string) => {
    setDetail(null)
    setDetailStatus("loading")
    setDetailError(null)
    setSelectedTraceId(traceId)
  }, [])

  const closeTrace = useCallback(() => {
    setSelectedTraceId(null)
    setDetail(null)
    setDetailStatus("idle")
    setDetailError(null)
  }, [])

  const retryDetail = useCallback(() => setDetailToken((token) => token + 1), [])

  return {
    filter,
    setFilter,
    summaries,
    listStatus,
    listError,
    refresh,
    selectedTraceId,
    detail,
    detailStatus,
    detailError,
    openTrace,
    closeTrace,
    retryDetail,
  }
}
