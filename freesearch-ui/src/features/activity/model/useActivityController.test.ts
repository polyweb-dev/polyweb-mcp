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
} from "@/test/fixtures/activity"

/**
 * Cache-backed Activity coordination (PLAN §5): the list loads on mount and
 * refetches on filter change; a detail loads lazily the first time it is
 * needed — by expansion or by dialog — and is then cached, so Inspect reuses
 * the parent's decoded detail. Concurrent requests dedupe, every request
 * aborts cleanly, and stale responses only ever write to their own id.
 */
function stubTraces(options?: {
  detailHandler?: (traceId: string) => Response | Promise<Response>
  listHandler?: () => Response | Promise<Response>
}) {
  return installFetchStub((req) => {
    if (req.method === "GET" && req.url.startsWith("/api/v1/traces/")) {
      const traceId = decodeURIComponent(req.url.split("/").pop() ?? "")
      if (options?.detailHandler) return options.detailHandler(traceId)
      if (traceId === SUCCESS_TRACE_ID) return ok(traceDetailFixture())
      if (traceId === ERROR_TRACE_ID) return ok(errorTraceDetailFixture())
      if (traceId === AGGREGATED_TRACE_ID) return ok(aggregatedTraceDetailFixture())
      return err(404, { detail: `unknown trace '${traceId}'` })
    }
    if (req.method === "GET" && req.url.startsWith("/api/v1/traces")) {
      if (options?.listHandler) return options.listHandler()
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
    const { result } = renderHook(() => useActivityController())

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
    const { result } = renderHook(() => useActivityController())

    await waitFor(() => {
      expect(result.current.listStatus).toBe("ready")
    })
    expect(stub.requestsTo("/api/v1/traces?limit=50")).toHaveLength(1)
  })

  it("refetches with the operation filter when the filter changes", async () => {
    const stub = stubTraces()
    const { result } = renderHook(() => useActivityController())

    await waitFor(() => {
      expect(result.current.listStatus).toBe("ready")
    })

    act(() => {
      result.current.setFilter("fetch")
    })
    await waitFor(() => {
      expect(
        stub.requestsTo("/api/v1/traces?limit=50&operation=fetch")
      ).toHaveLength(1)
    })
    expect(result.current.filter).toBe("fetch")
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
    const { result } = renderHook(() => useActivityController())

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
    const { result } = renderHook(() => useActivityController())

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
    const { result } = renderHook(() => useActivityController())

    await waitFor(() => {
      expect(gates).toHaveLength(1)
    })

    act(() => {
      result.current.setFilter("fetch")
    })
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
    const { result } = renderHook(() => useActivityController())

    await waitFor(() => {
      expect(result.current.listStatus).toBe("ready")
    })
    expect(
      stub.requests.filter((req) => req.url.includes("/api/v1/traces/"))
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
    const { result } = renderHook(() => useActivityController())

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
    const { result } = renderHook(() => useActivityController())

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
    const { result } = renderHook(() => useActivityController())

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
    const { result } = renderHook(() => useActivityController())

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
    const { result } = renderHook(() => useActivityController())

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
    const { result } = renderHook(() => useActivityController())

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
    const { result } = renderHook(() => useActivityController())

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
      if (req.method === "GET" && req.url.startsWith("/api/v1/traces/")) {
        const traceId = decodeURIComponent(req.url.split("/").pop() ?? "")
        const gate = deferred<Response>()
        gates.set(traceId, gate)
        return gate.promise
      }
      if (req.method === "GET" && req.url.startsWith("/api/v1/traces")) {
        return ok(traceListFixture())
      }
      return err(404, { detail: "unhandled test route" })
    })
    const { result } = renderHook(() => useActivityController())

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
    const { unmount } = renderHook(() => useActivityController())

    unmount()
    await act(async () => {
      gate.resolve(ok(traceListFixture()))
    })
  })
})
