import { useCallback, useEffect, useRef, useState } from "react"
import { listProjectTraces, type TraceListQuery, type TraceSummary } from "@/domains/activity"
import { errorMessage } from "@/shared/api/http"
import type { ActivityFilters } from "./activityFilters"

export type LoadStatus = "loading" | "ready" | "error"
export type MoreStatus = "idle" | "loading" | "error"

/** Page size of the Activity list. */
export const TRACE_PAGE_SIZE = 50

interface TraceListState {
  summaries: TraceSummary[]
  nextCursor: string | null
  listStatus: LoadStatus
  listError: string | null
  moreStatus: MoreStatus
  moreError: string | null
}

const FIRST_PAGE_LOADING: TraceListState = {
  summaries: [],
  nextCursor: null,
  listStatus: "loading",
  listError: null,
  moreStatus: "idle",
  moreError: null,
}

/** Append one page, skipping a row an overlapping page already holds. */
function appendPage(rows: TraceSummary[], page: TraceSummary[]): TraceSummary[] {
  const known = new Set(rows.map((row) => row.traceId))
  return [...rows, ...page.filter((row) => !known.has(row.traceId))]
}

/**
 * The newest-first summary list of one project with cursor pagination.
 *
 * The project, a filter, or the refresh token resets the list to page one and
 * aborts every request of the previous list; `loadMore` appends the next
 * cursor page. A generation counter drops every late page of a previous list,
 * so a client that resolves after an abort can never publish stale rows.
 */
export function useTraceList(projectId: string, filters: ActivityFilters, reloadToken: number) {
  const { operation, outcome } = filters
  const [state, setState] = useState<TraceListState>(FIRST_PAGE_LOADING)
  const generationRef = useRef(0)
  const moreRef = useRef<AbortController | null>(null)
  const stateRef = useRef(state)

  useEffect(() => {
    stateRef.current = state
  })

  const pageQuery = useCallback(
    (cursor: string | null): TraceListQuery => ({
      limit: TRACE_PAGE_SIZE,
      ...(operation === null ? {} : { operation }),
      ...(outcome === null ? {} : { outcome }),
      ...(cursor === null ? {} : { cursor }),
    }),
    [operation, outcome]
  )

  useEffect(() => {
    generationRef.current += 1
    const generation = generationRef.current
    const controller = new AbortController()
    const load = async () => {
      setState(FIRST_PAGE_LOADING)
      try {
        const page = await listProjectTraces(projectId, pageQuery(null), controller.signal)
        if (controller.signal.aborted || generation !== generationRef.current) return
        setState({
          ...FIRST_PAGE_LOADING,
          summaries: page.items,
          nextCursor: page.nextCursor,
          listStatus: "ready",
        })
      } catch (error) {
        // Only this list's own abort is silent; a timeout or failure shows Retry.
        if (controller.signal.aborted || generation !== generationRef.current) return
        setState({
          ...FIRST_PAGE_LOADING,
          listStatus: "error",
          listError: errorMessage(error, "Traces unavailable"),
        })
      }
    }
    void load()
    return () => {
      controller.abort()
      moreRef.current?.abort()
      moreRef.current = null
    }
  }, [projectId, pageQuery, reloadToken])

  const loadMore = useCallback(() => {
    const { listStatus, nextCursor } = stateRef.current
    if (listStatus !== "ready" || nextCursor === null || moreRef.current !== null) return
    const generation = generationRef.current
    const controller = new AbortController()
    moreRef.current = controller
    setState((current) => ({ ...current, moreStatus: "loading", moreError: null }))
    void (async () => {
      try {
        const page = await listProjectTraces(projectId, pageQuery(nextCursor), controller.signal)
        if (controller.signal.aborted || generation !== generationRef.current) return
        setState((current) => ({
          ...current,
          summaries: appendPage(current.summaries, page.items),
          nextCursor: page.nextCursor,
          moreStatus: "idle",
        }))
      } catch (error) {
        if (controller.signal.aborted || generation !== generationRef.current) return
        setState((current) => ({
          ...current,
          moreStatus: "error",
          moreError: errorMessage(error, "More traces unavailable"),
        }))
      } finally {
        if (moreRef.current === controller) moreRef.current = null
      }
    })()
  }, [projectId, pageQuery])

  return {
    summaries: state.summaries,
    listStatus: state.listStatus,
    listError: state.listError,
    hasMore: state.nextCursor !== null,
    moreStatus: state.moreStatus,
    moreError: state.moreError,
    loadMore,
  }
}
