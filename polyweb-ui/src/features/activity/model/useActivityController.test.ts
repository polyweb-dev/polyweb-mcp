import { describe, expect, it, afterEach, vi } from "vitest"
import { act, renderHook, waitFor } from "@testing-library/react"
import { selectedTraceState, useActivityController } from "./useActivityController"
import { deferred, err, installFetchStub, ok } from "@/test/fetchMock"
import {
  AGGREGATED_TRACE_ID,
  ERROR_TRACE_ID,
  SUCCESS_TRACE_ID,
  aggregatedTraceDetailFixture,
  errorTraceDetailFixture,
  traceDetailFixture,
  traceListFixture,
  traceSummaryFixture,
} from "@/test/fixtures/activity"
import { PROJECT_ALPHA_ID, PROJECT_BETA_ID } from "@/test/accessFixtures"
import type { ActivityFilters } from "./activityFilters"

const TRACES = `/api/v1/projects/${PROJECT_ALPHA_ID}/traces`
const ALL: ActivityFilters = { operation: null, outcome: null }

/** Render the controller of one project; `rerender` takes new filters. */
function renderController(filters: ActivityFilters = ALL, projectId: string = PROJECT_ALPHA_ID) {
  return renderHook(
    (props: { projectId: string; filters: ActivityFilters }) =>
      useActivityController(props.projectId, props.filters),
    { initialProps: { projectId, filters } }
  )
}

/**
 * Cache-backed Activity coordination (PLAN §5): the list loads on mount and
 * refetches on filter change; a detail loads lazily the first time it is
 * needed — by expansion or by dialog — and is then cached, so Inspect reuses
 * the parent's decoded detail. Concurrent requests dedupe, every request
 * aborts cleanly, and stale responses only ever write to their own id.
 */
function stubTraces(options?: {
  detailHandler?: (traceId: string) => Response | Promise<Response>
  listHandler?: (url: string) => Response | Promise<Response>
}) {
  return installFetchStub((req) => {
    if (req.method === "GET" && /^\/api\/v1\/projects\/[^/]+\/traces\//.test(req.url)) {
      const traceId = decodeURIComponent(req.url.split("/").pop() ?? "")
      if (options?.detailHandler) return options.detailHandler(traceId)
      if (traceId === SUCCESS_TRACE_ID) return ok(traceDetailFixture())
      if (traceId === ERROR_TRACE_ID) return ok(errorTraceDetailFixture())
      if (traceId === AGGREGATED_TRACE_ID) return ok(aggregatedTraceDetailFixture())
      return err(404, { detail: `unknown trace '${traceId}'` })
    }
    if (req.method === "GET" && /^\/api\/v1\/projects\/[^/]+\/traces/.test(req.url)) {
      if (options?.listHandler) return options.listHandler(req.url)
      return ok(traceListFixture())
    }
    return err(404, { detail: "unhandled test route" })
  })
}

describe("useActivityController list", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("starts loading and reaches ready with decoded summaries", async () => {
    const gate = deferred<Response>()
    stubTraces({ listHandler: () => gate.promise })
    const { result } = renderController()

    expect(result.current.listStatus).toBe("loading")

    await act(async () => {
      gate.resolve(ok(traceListFixture()))
    })
    await waitFor(() => {
      expect(result.current.listStatus).toBe("ready")
    })
    expect(result.current.summaries.map((summary) => summary.traceId)).toEqual([
      AGGREGATED_TRACE_ID,
      SUCCESS_TRACE_ID,
      ERROR_TRACE_ID,
    ])
    expect(result.current.listError).toBeNull()
  })

  it("requests the default list limit without an operation filter", async () => {
    const stub = stubTraces()
    const { result } = renderController()

    await waitFor(() => {
      expect(result.current.listStatus).toBe("ready")
    })
    expect(stub.requestsTo(`${TRACES}?limit=50`)).toHaveLength(1)
  })

  it("refetches with the operation filter when the filter changes", async () => {
    const stub = stubTraces()
    const { result, rerender } = renderController()

    await waitFor(() => {
      expect(result.current.listStatus).toBe("ready")
    })

    rerender({ projectId: PROJECT_ALPHA_ID, filters: { operation: "fetch", outcome: null } })
    await waitFor(() => {
      expect(stub.requestsTo(`${TRACES}?limit=50&operation=fetch`)).toHaveLength(1)
    })
  })

  it("sends both filters and resets to page one when a filter changes", async () => {
    const stub = stubTraces({
      listHandler: (url) =>
        ok(traceListFixture({ next_cursor: url.includes("cursor=") ? null : "page-2" })),
    })
    const { result, rerender } = renderController({ operation: "search", outcome: "error" })

    await waitFor(() => {
      expect(result.current.hasMore).toBe(true)
    })
    expect(stub.requestsTo(`${TRACES}?limit=50&operation=search&outcome=error`)).toHaveLength(1)

    rerender({ projectId: PROJECT_ALPHA_ID, filters: { operation: null, outcome: "partial" } })
    await waitFor(() => {
      expect(stub.requestsTo(`${TRACES}?limit=50&outcome=partial`)).toHaveLength(1)
    })
    expect(stub.requests.some((req) => req.url.includes("cursor="))).toBe(false)
  })

  it("surfaces list errors and retries through refresh", async () => {
    let calls = 0
    stubTraces({
      listHandler: () => {
        calls += 1
        return calls === 1
          ? err(503, { detail: "traces unavailable" })
          : ok(traceListFixture())
      },
    })
    const { result } = renderController()

    await waitFor(() => {
      expect(result.current.listStatus).toBe("error")
    })
    expect(result.current.listError).toContain("traces unavailable")

    act(() => {
      result.current.refresh()
    })
    await waitFor(() => {
      expect(result.current.listStatus).toBe("ready")
    })
    expect(result.current.summaries).toHaveLength(3)
  })

  it("resolves an empty list to ready with no summaries", async () => {
    stubTraces({ listHandler: () => ok({ items: [], generated_at: "x" }) })
    const { result } = renderController()

    await waitFor(() => {
      expect(result.current.listStatus).toBe("ready")
    })
    expect(result.current.summaries).toEqual([])
  })

  it("drops a late list response that resolves after a filter change", async () => {
    const gates: Array<ReturnType<typeof deferred<Response>>> = []
    stubTraces({
      listHandler: () => {
        const gate = deferred<Response>()
        gates.push(gate)
        return gate.promise
      },
    })
    const { result, rerender } = renderController()

    await waitFor(() => {
      expect(gates).toHaveLength(1)
    })

    rerender({ projectId: PROJECT_ALPHA_ID, filters: { operation: "fetch", outcome: null } })
    await waitFor(() => {
      expect(gates).toHaveLength(2)
    })

    await act(async () => {
      gates[0]?.resolve(ok(traceListFixture()))
    })
    expect(result.current.summaries).toEqual([])
    expect(result.current.listStatus).toBe("loading")

    await act(async () => {
      gates[1]?.resolve(ok(traceListFixture()))
    })
    await waitFor(() => {
      expect(result.current.listStatus).toBe("ready")
    })
    expect(result.current.summaries.map((summary) => summary.traceId)).toEqual([
      AGGREGATED_TRACE_ID,
      SUCCESS_TRACE_ID,
      ERROR_TRACE_ID,
    ])
  })
})

describe("useActivityController expansion and detail cache", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("loads detail lazily on expansion and exposes it through detailsById", async () => {
    const stub = stubTraces()
    const { result } = renderController()

    await waitFor(() => {
      expect(result.current.listStatus).toBe("ready")
    })
    expect(
      stub.requests.filter((req) => req.url.includes(`${TRACES}/`))
    ).toHaveLength(0)
    expect(result.current.expandedTraceId).toBeNull()

    act(() => {
      result.current.toggleProviders(AGGREGATED_TRACE_ID)
    })
    expect(result.current.expandedTraceId).toBe(AGGREGATED_TRACE_ID)
    await waitFor(() => {
      expect(result.current.detailsById[AGGREGATED_TRACE_ID]?.status).toBe("ready")
    })
    expect(
      result.current.detailsById[AGGREGATED_TRACE_ID]?.detail?.traceId
    ).toBe(AGGREGATED_TRACE_ID)
  })

  it("collapses when the same parent is toggled twice", async () => {
    stubTraces()
    const { result } = renderController()

    await waitFor(() => {
      expect(result.current.listStatus).toBe("ready")
    })

    act(() => {
      result.current.toggleProviders(AGGREGATED_TRACE_ID)
    })
    expect(result.current.expandedTraceId).toBe(AGGREGATED_TRACE_ID)
    act(() => {
      result.current.toggleProviders(AGGREGATED_TRACE_ID)
    })
    expect(result.current.expandedTraceId).toBeNull()
  })

  it("keeps only one expanded parent at a time", async () => {
    stubTraces()
    const { result } = renderController()

    await waitFor(() => {
      expect(result.current.listStatus).toBe("ready")
    })

    act(() => {
      result.current.toggleProviders(AGGREGATED_TRACE_ID)
    })
    act(() => {
      result.current.toggleProviders(SUCCESS_TRACE_ID)
    })
    expect(result.current.expandedTraceId).toBe(SUCCESS_TRACE_ID)
  })

  it("dedupes concurrent detail requests for the same trace", async () => {
    const gate = deferred<Response>()
    let calls = 0
    stubTraces({
      detailHandler: () => {
        calls += 1
        return gate.promise
      },
    })
    const { result } = renderController()

    await waitFor(() => {
      expect(result.current.listStatus).toBe("ready")
    })

    act(() => {
      result.current.toggleProviders(AGGREGATED_TRACE_ID)
    })
    act(() => {
      result.current.openTrace(AGGREGATED_TRACE_ID)
    })
    expect(calls).toBe(1)

    await act(async () => {
      gate.resolve(ok(aggregatedTraceDetailFixture()))
    })
    await waitFor(() => {
      expect(result.current.detailsById[AGGREGATED_TRACE_ID]?.status).toBe("ready")
    })
  })

  it("reuses the cached expansion detail when the dialog opens (Inspect path)", async () => {
    let calls = 0
    stubTraces({
      detailHandler: () => {
        calls += 1
        return ok(aggregatedTraceDetailFixture())
      },
    })
    const { result } = renderController()

    await waitFor(() => {
      expect(result.current.listStatus).toBe("ready")
    })

    act(() => {
      result.current.toggleProviders(AGGREGATED_TRACE_ID)
    })
    await waitFor(() => {
      expect(result.current.detailsById[AGGREGATED_TRACE_ID]?.status).toBe("ready")
    })
    expect(calls).toBe(1)

    // Inspect reuses the parent's decoded detail instead of refetching it.
    act(() => {
      result.current.openTrace(AGGREGATED_TRACE_ID, "a100000000000003")
    })
    expect(result.current.selection).toEqual({
      traceId: AGGREGATED_TRACE_ID,
      providerSpanId: "a100000000000003",
    })
    expect(calls).toBe(1)
    expect(selectedTraceState(result.current).detail?.traceId).toBe(AGGREGATED_TRACE_ID)
  })

  it("opens a whole-trace selection with a null provider scope", async () => {
    stubTraces()
    const { result } = renderController()

    await waitFor(() => {
      expect(result.current.listStatus).toBe("ready")
    })

    act(() => {
      result.current.openTrace(SUCCESS_TRACE_ID)
    })
    expect(result.current.selection).toEqual({
      traceId: SUCCESS_TRACE_ID,
      providerSpanId: null,
    })
    await waitFor(() => {
      expect(selectedTraceState(result.current).status).toBe("ready")
    })
    expect(selectedTraceState(result.current).detail?.input).toBe(
      "distributed consensus algorithms"
    )

    act(() => {
      result.current.closeTrace()
    })
    expect(result.current.selection).toBeNull()
    expect(selectedTraceState(result.current).status).toBe("idle")
  })

  it("retries a failed detail through retryTrace", async () => {
    let calls = 0
    stubTraces({
      detailHandler: () => {
        calls += 1
        return calls === 1
          ? err(500, { detail: "detail blew up" })
          : ok(traceDetailFixture())
      },
    })
    const { result } = renderController()

    await waitFor(() => {
      expect(result.current.listStatus).toBe("ready")
    })

    act(() => {
      result.current.openTrace(SUCCESS_TRACE_ID)
    })
    await waitFor(() => {
      expect(result.current.detailsById[SUCCESS_TRACE_ID]?.status).toBe("error")
    })
    expect(result.current.detailsById[SUCCESS_TRACE_ID]?.error).toContain("detail blew up")

    act(() => {
      result.current.retryTrace(SUCCESS_TRACE_ID)
    })
    await waitFor(() => {
      expect(result.current.detailsById[SUCCESS_TRACE_ID]?.status).toBe("ready")
    })
    expect(result.current.detailsById[SUCCESS_TRACE_ID]?.detail?.traceId).toBe(
      SUCCESS_TRACE_ID
    )
  })

  it("clears cache, expansion, and selection on refresh", async () => {
    stubTraces()
    const { result } = renderController()

    await waitFor(() => {
      expect(result.current.listStatus).toBe("ready")
    })

    act(() => {
      result.current.toggleProviders(AGGREGATED_TRACE_ID)
    })
    await waitFor(() => {
      expect(result.current.detailsById[AGGREGATED_TRACE_ID]?.status).toBe("ready")
    })
    act(() => {
      result.current.openTrace(AGGREGATED_TRACE_ID, "a100000000000003")
    })
    expect(result.current.selection).not.toBeNull()

    act(() => {
      result.current.refresh()
    })
    expect(result.current.detailsById).toEqual({})
    expect(result.current.expandedTraceId).toBeNull()
    expect(result.current.selection).toBeNull()
  })

  it("drops a stale detail response that resolves after opening another trace", async () => {
    const gates = new Map<string, ReturnType<typeof deferred<Response>>>()
    installFetchStub((req) => {
      if (req.method === "GET" && req.url.startsWith(`${TRACES}/`)) {
        const traceId = decodeURIComponent(req.url.split("/").pop() ?? "")
        const gate = deferred<Response>()
        gates.set(traceId, gate)
        return gate.promise
      }
      if (req.method === "GET" && req.url.startsWith(TRACES)) {
        return ok(traceListFixture())
      }
      return err(404, { detail: "unhandled test route" })
    })
    const { result } = renderController()

    await waitFor(() => {
      expect(result.current.listStatus).toBe("ready")
    })

    act(() => {
      result.current.openTrace(SUCCESS_TRACE_ID)
    })
    await waitFor(() => {
      expect(gates.has(SUCCESS_TRACE_ID)).toBe(true)
    })

    // Opening another trace aborts the first; its late resolution must never
    // publish the old detail. Per-id state means the stale write lands on its
    // own key only if it was still the active request — aborted, it is dropped.
    act(() => {
      result.current.openTrace(ERROR_TRACE_ID)
    })
    await waitFor(() => {
      expect(gates.has(ERROR_TRACE_ID)).toBe(true)
    })

    await act(async () => {
      gates.get(ERROR_TRACE_ID)?.resolve(ok(errorTraceDetailFixture()))
    })
    await waitFor(() => {
      expect(result.current.detailsById[ERROR_TRACE_ID]?.status).toBe("ready")
    })
    expect(result.current.detailsById[ERROR_TRACE_ID]?.detail?.traceId).toBe(ERROR_TRACE_ID)
    // The first id never reached ready from its abandoned request.
    expect(result.current.detailsById[SUCCESS_TRACE_ID]?.status).toBe("loading")
  })

  it("aborts in-flight requests on unmount without crashing", async () => {
    const gate = deferred<Response>()
    stubTraces({ listHandler: () => gate.promise })
    const { unmount } = renderController()

    unmount()
    await act(async () => {
      gate.resolve(ok(traceListFixture()))
    })
  })
})

describe("useActivityController pages, retention and project scope", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function pagedStub() {
    return stubTraces({
      listHandler: (url) => {
        if (!url.includes("cursor=")) return ok(traceListFixture({ next_cursor: "page-2" }))
        return ok({
          items: [{ ...traceSummaryFixture(), trace_id: "f".repeat(32) }],
          generated_at: "2026-09-06T10:00:00Z",
          next_cursor: null,
        })
      },
    })
  }

  it("appends the next cursor page on loadMore and stops at the last page", async () => {
    const stub = pagedStub()
    const { result } = renderController({ operation: "search", outcome: null })

    await waitFor(() => {
      expect(result.current.hasMore).toBe(true)
    })
    expect(result.current.summaries).toHaveLength(3)

    act(() => {
      result.current.loadMore()
    })
    await waitFor(() => {
      expect(result.current.summaries).toHaveLength(4)
    })
    expect(result.current.hasMore).toBe(false)
    expect(result.current.summaries[3]?.traceId).toBe("f".repeat(32))
    expect(stub.requestsTo(`${TRACES}?limit=50&operation=search&cursor=page-2`)).toHaveLength(1)
  })

  it("keeps every loaded row after the detail closes", async () => {
    pagedStub()
    const { result } = renderController()
    await waitFor(() => {
      expect(result.current.hasMore).toBe(true)
    })
    act(() => {
      result.current.loadMore()
    })
    await waitFor(() => {
      expect(result.current.summaries).toHaveLength(4)
    })

    act(() => {
      result.current.openTrace(SUCCESS_TRACE_ID)
    })
    await waitFor(() => {
      expect(selectedTraceState(result.current).status).toBe("ready")
    })
    act(() => {
      result.current.closeTrace()
    })

    expect(result.current.selection).toBeNull()
    expect(result.current.summaries).toHaveLength(4)
    expect(result.current.hasMore).toBe(false)
  })

  it("marks a trace of another project as missing with the project copy", async () => {
    stubTraces({ detailHandler: () => err(404, { detail: "no trace" }) })
    const { result } = renderController()
    await waitFor(() => {
      expect(result.current.listStatus).toBe("ready")
    })

    act(() => {
      result.current.openTrace(SUCCESS_TRACE_ID)
    })
    await waitFor(() => {
      expect(selectedTraceState(result.current).status).toBe("missing")
    })
    expect(selectedTraceState(result.current).error).toBe(
      "This trace is not available in this project."
    )
  })

  it("aborts the old project's list on a switch and ignores its late page", async () => {
    const gates = new Map<string, ReturnType<typeof deferred<Response>>>()
    const stub = stubTraces({
      listHandler: (url) => {
        const gate = deferred<Response>()
        gates.set(url, gate)
        return gate.promise
      },
    })
    const { result, rerender } = renderController()
    await waitFor(() => {
      expect(gates.size).toBe(1)
    })
    const alphaRequest = stub.requests[0]

    rerender({ projectId: PROJECT_BETA_ID, filters: ALL })
    await waitFor(() => {
      expect(gates.size).toBe(2)
    })
    expect(alphaRequest?.signal?.aborted).toBe(true)

    await act(async () => {
      gates.get(`${TRACES}?limit=50`)?.resolve(ok(traceListFixture()))
    })
    expect(result.current.listStatus).toBe("loading")
    expect(result.current.summaries).toEqual([])
  })

  it("keys the detail cache by project, so another project never reuses a detail", async () => {
    const stub = stubTraces()
    const { result, rerender } = renderController()
    await waitFor(() => {
      expect(result.current.listStatus).toBe("ready")
    })
    act(() => {
      result.current.openTrace(SUCCESS_TRACE_ID)
    })
    await waitFor(() => {
      expect(result.current.detailsById[SUCCESS_TRACE_ID]?.status).toBe("ready")
    })

    rerender({ projectId: PROJECT_BETA_ID, filters: ALL })
    expect(result.current.detailsById[SUCCESS_TRACE_ID]).toBeUndefined()
    act(() => {
      result.current.openTrace(SUCCESS_TRACE_ID)
    })
    await waitFor(() => {
      expect(
        stub.requestsTo(`/api/v1/projects/${PROJECT_BETA_ID}/traces/${SUCCESS_TRACE_ID}`)
      ).toHaveLength(1)
    })
  })
})
