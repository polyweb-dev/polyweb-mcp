import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  TRACE_NOT_IN_PROJECT_MESSAGE,
  getProjectTrace,
  isTraceNotFound,
  type TraceDetail,
  type TraceSummary,
} from "@/domains/activity"
import { errorMessage } from "@/shared/api/http"
import type { ActivityFilters } from "./activityFilters"
import { useTraceList } from "./useTraceList"
import type { LoadStatus, MoreStatus } from "./useTraceList"

export type { LoadStatus, MoreStatus }
export type DetailStatus = "idle" | LoadStatus | "missing"

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
  summaries: TraceSummary[]
  listStatus: LoadStatus
  listError: string | null
  hasMore: boolean
  moreStatus: MoreStatus
  moreError: string | null
  loadMore: () => void
  refresh: () => void
  detailsById: Readonly<Record<string, TraceLoadState>>
  expandedTraceId: string | null
  selection: TraceSelection | null
  toggleProviders: (traceId: string) => void
  retryTrace: (traceId: string) => void
  openTrace: (traceId: string, providerSpanId?: string) => void
  closeTrace: () => void
}

const IDLE_DETAIL: TraceLoadState = { status: "idle", detail: null, error: null }

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

/** Cache key of one trace detail: the project is part of the identity. */
function detailKey(projectId: string, traceId: string): string {
  return `${projectId}:${traceId}`
}

/** The cached details of one project, keyed by trace id for the views. */
function detailsOfProject(
  cache: Readonly<Record<string, TraceLoadState>>,
  projectId: string
): Record<string, TraceLoadState> {
  const prefix = `${projectId}:`
  const details: Record<string, TraceLoadState> = {}
  for (const [key, state] of Object.entries(cache)) {
    if (key.startsWith(prefix)) details[key.slice(prefix.length)] = state
  }
  return details
}

function failedDetail(error: unknown): TraceLoadState {
  if (isTraceNotFound(error)) {
    return { status: "missing", detail: null, error: TRACE_NOT_IN_PROJECT_MESSAGE }
  }
  return { status: "error", detail: null, error: errorMessage(error, "Trace detail unavailable") }
}

/**
 * Activity list/detail coordination of one project. The list loads page one
 * whenever the project or a filter changes and appends cursor pages on "Load
 * more"; a detail loads lazily the first time it is needed — either by
 * expanding a fanout row or by opening the dialog — and is then cached, so
 * inspecting a provider reuses the parent's already-decoded detail. Closing
 * the dialog only clears the selection, so the filters and every loaded row
 * stay. The cache is keyed by `projectId:traceId`, so one project's detail can
 * never answer another's, even without the project remount. Concurrent
 * requests for one id are deduped, every request is abortable, and a stale
 * response can only ever write to its own id.
 */
export function useActivityController(
  projectId: string,
  filters: ActivityFilters
): ActivityController {
  const [reloadToken, setReloadToken] = useState(0)
  const list = useTraceList(projectId, filters, reloadToken)
  const [detailCache, setDetailCache] = useState<Record<string, TraceLoadState>>({})
  const [expandedTraceId, setExpandedTraceId] = useState<string | null>(null)
  const [selection, setSelection] = useState<TraceSelection | null>(null)

  // Mirrors of the state the loader must read synchronously without becoming a
  // dependency of `loadDetail` (which would re-create it on every response).
  const detailsRef = useRef<Record<string, TraceLoadState>>({})
  const expandedRef = useRef<string | null>(null)
  const requestsRef = useRef(new Map<string, AbortController>())

  const publish = useCallback((key: string, state: TraceLoadState) => {
    detailsRef.current = { ...detailsRef.current, [key]: state }
    setDetailCache(detailsRef.current)
  }, [])

  const loadDetail = useCallback(
    (traceId: string, force = false) => {
      const key = detailKey(projectId, traceId)
      if (requestsRef.current.has(key)) return
      const cached = detailsRef.current[key]
      if (!force && cached?.status === "ready") return
      const controller = new AbortController()
      requestsRef.current.set(key, controller)
      publish(key, { status: "loading", detail: cached?.detail ?? null, error: null })
      void (async () => {
        try {
          const detail = await getProjectTrace(projectId, traceId, controller.signal)
          if (controller.signal.aborted) return
          publish(key, { status: "ready", detail, error: null })
        } catch (error) {
          // Only this request's own abort is silent; a timeout shows Retry.
          if (controller.signal.aborted) return
          publish(key, failedDetail(error))
        } finally {
          if (requestsRef.current.get(key) === controller) requestsRef.current.delete(key)
        }
      })()
    },
    [projectId, publish]
  )

  const detailsById = useMemo(() => detailsOfProject(detailCache, projectId), [detailCache, projectId])

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
    setDetailCache({})
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
    ...list,
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
