import { useCallback, useEffect, useRef, useState } from "react"
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

/** Per-trace detail state; the list expansion and the dialog share one cache. */
export interface TraceLoadState {
  status: DetailStatus
  detail: TraceDetail | null
  error: string | null
}

/** What the detail dialog is scoped to: a whole trace, or one provider attempt. */
export interface TraceSelection {
  traceId: string
  providerSpanId: string | null
}

export interface ActivityController {
  filter: ActivityFilter
  setFilter: (filter: ActivityFilter) => void
  summaries: TraceSummary[]
  listStatus: LoadStatus
  listError: string | null
  refresh: () => void
  detailsById: Readonly<Record<string, TraceLoadState>>
  expandedTraceId: string | null
  selection: TraceSelection | null
  toggleProviders: (traceId: string) => void
  retryTrace: (traceId: string) => void
  openTrace: (traceId: string, providerSpanId?: string) => void
  closeTrace: () => void
}

const LIST_LIMIT = 50
const IDLE_DETAIL: TraceLoadState = { status: "idle", detail: null, error: null }

interface TraceListState {
  summaries: TraceSummary[]
  listStatus: LoadStatus
  listError: string | null
}

/**
 * The summary list: loads on mount and whenever the filter or the explicit
 * refresh token changes. Abort semantics belong to this hook, not to the
 * transport: a client that resolves after an abort (stub, custom transport, or
 * a resolve-then-abort race) must not publish a stale list.
 */
function useTraceList(filter: ActivityFilter, reloadToken: number): TraceListState {
  const [summaries, setSummaries] = useState<TraceSummary[]>([])
  const [listStatus, setListStatus] = useState<LoadStatus>("loading")
  const [listError, setListError] = useState<string | null>(null)

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

  return { summaries, listStatus, listError }
}

/**
 * Detail state for the current selection. Opening a trace publishes a loading
 * state immediately, so a live selection without a cached entry is loading.
 */
export function selectedTraceState(controller: ActivityController): TraceLoadState {
  if (controller.selection === null) return IDLE_DETAIL
  return controller.detailsById[controller.selection.traceId] ?? {
    status: "loading",
    detail: null,
    error: null,
  }
}

/**
 * Activity list/detail coordination. The list loads on mount and whenever the
 * filter changes; a detail loads lazily the first time it is needed — either by
 * expanding a fanout row or by opening the dialog — and is then cached, so
 * inspecting a provider reuses the parent's already-decoded detail instead of
 * refetching it. Concurrent requests for one id are deduped, every request is
 * abortable, and a stale response can only ever write to its own id.
 */
export function useActivityController(): ActivityController {
  const [filter, setFilter] = useState<ActivityFilter>("all")
  const [reloadToken, setReloadToken] = useState(0)
  const { summaries, listStatus, listError } = useTraceList(filter, reloadToken)
  const [detailsById, setDetailsById] = useState<Record<string, TraceLoadState>>({})
  const [expandedTraceId, setExpandedTraceId] = useState<string | null>(null)
  const [selection, setSelection] = useState<TraceSelection | null>(null)

  // Mirrors of the state the loader must read synchronously without becoming a
  // dependency of `loadDetail` (which would re-create it on every response).
  const detailsRef = useRef<Record<string, TraceLoadState>>({})
  const expandedRef = useRef<string | null>(null)
  const requestsRef = useRef(new Map<string, AbortController>())

  const publish = useCallback((traceId: string, state: TraceLoadState) => {
    detailsRef.current = { ...detailsRef.current, [traceId]: state }
    setDetailsById(detailsRef.current)
  }, [])

  const loadDetail = useCallback(
    (traceId: string, force = false) => {
      if (requestsRef.current.has(traceId)) return
      const cached = detailsRef.current[traceId]
      if (!force && cached?.status === "ready") return
      const controller = new AbortController()
      requestsRef.current.set(traceId, controller)
      publish(traceId, { status: "loading", detail: cached?.detail ?? null, error: null })
      void (async () => {
        try {
          const payload = await apiService.getTrace(traceId, controller.signal)
          if (controller.signal.aborted) return
          publish(traceId, { status: "ready", detail: mapTraceDetail(payload), error: null })
        } catch (error) {
          if (controller.signal.aborted || isAbortOrTimeout(error)) return
          publish(traceId, {
            status: "error",
            detail: null,
            error: errorMessage(error, "Trace detail unavailable"),
          })
        } finally {
          if (requestsRef.current.get(traceId) === controller) requestsRef.current.delete(traceId)
        }
      })()
    },
    [publish]
  )

  useEffect(() => {
    const requests = requestsRef.current
    return () => {
      for (const controller of requests.values()) controller.abort()
      requests.clear()
    }
  }, [])

  const refresh = useCallback(() => {
    for (const controller of requestsRef.current.values()) controller.abort()
    requestsRef.current.clear()
    detailsRef.current = {}
    expandedRef.current = null
    setDetailsById({})
    setExpandedTraceId(null)
    setSelection(null)
    setReloadToken((token) => token + 1)
  }, [])

  const toggleProviders = useCallback(
    (traceId: string) => {
      // One expanded parent at a time: opening another collapses the previous.
      const next = expandedRef.current === traceId ? null : traceId
      expandedRef.current = next
      setExpandedTraceId(next)
      if (next !== null) loadDetail(traceId)
    },
    [loadDetail]
  )

  const retryTrace = useCallback(
    (traceId: string) => loadDetail(traceId, true),
    [loadDetail]
  )

  const openTrace = useCallback(
    (traceId: string, providerSpanId?: string) => {
      setSelection({ traceId, providerSpanId: providerSpanId ?? null })
      loadDetail(traceId)
    },
    [loadDetail]
  )

  const closeTrace = useCallback(() => setSelection(null), [])

  return {
    filter,
    setFilter,
    summaries,
    listStatus,
    listError,
    refresh,
    detailsById,
    expandedTraceId,
    selection,
    toggleProviders,
    retryTrace,
    openTrace,
    closeTrace,
  }
}
