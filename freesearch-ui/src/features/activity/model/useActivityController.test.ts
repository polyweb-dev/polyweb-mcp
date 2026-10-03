import { describe, expect, it, afterEach, vi } from "vitest"
import { act, renderHook, waitFor } from "@testing-library/react"
import { useActivityController } from "./useActivityController"
import { deferred, err, installFetchStub, ok } from "@/test/fetchMock"
import {
  ERROR_TRACE_ID,
  SUCCESS_TRACE_ID,
  errorTraceDetailFixture,
  traceDetailFixture,
  traceListFixture,
} from "@/test/fixtures/activity"

/**
 * Activity list/detail coordination. The list loads on mount and refetches on
 * filter change; detail stays idle until a trace is selected. Every request is
 * cancellable, so a stale detail response can never overwrite the selection.
 *
 * No context provider is involved: the controller is a local hook with the
 * shared fetch transport underneath, never a global mega-context.
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
    expect(result.current.summaries).toHaveLength(2)
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
    // Resolving-after-abort transport: the first request's stub ignores the
    // abort from the filter change and resolves late, so only the
    // controller's post-await aborted guard can drop the stale list.
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

    // The stale first response resolves late: it must publish neither its
    // rows nor a ready status while the current request is still pending.
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
      SUCCESS_TRACE_ID,
      ERROR_TRACE_ID,
    ])
  })
})

describe("useActivityController detail", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("fetches no detail before a selection is made", async () => {
    const stub = stubTraces()
    const { result } = renderHook(() => useActivityController())

    await waitFor(() => {
      expect(result.current.listStatus).toBe("ready")
    })
    expect(stub.requests.filter((req) => req.url.includes("/api/v1/traces/"))).toHaveLength(
      0
    )
    expect(result.current.selectedTraceId).toBeNull()
    expect(result.current.detailStatus).toBe("idle")
  })

  it("loads detail lazily on selection and clears it on close", async () => {
    stubTraces()
    const { result } = renderHook(() => useActivityController())

    await waitFor(() => {
      expect(result.current.listStatus).toBe("ready")
    })

    act(() => {
      result.current.openTrace(SUCCESS_TRACE_ID)
    })
    expect(result.current.selectedTraceId).toBe(SUCCESS_TRACE_ID)
    await waitFor(() => {
      expect(result.current.detailStatus).toBe("ready")
    })
    expect(result.current.detail?.traceId).toBe(SUCCESS_TRACE_ID)
    expect(result.current.detail?.input).toBe("distributed consensus algorithms")

    act(() => {
      result.current.closeTrace()
    })
    expect(result.current.selectedTraceId).toBeNull()
    expect(result.current.detail).toBeNull()
    expect(result.current.detailStatus).toBe("idle")
  })

  it("drops a stale detail response after reselecting another trace", async () => {
    // Faithful abort semantics: like a real fetch, an aborted request
    // rejects instead of resolving late, so the controller's stale guard
    // (aborted signal / AbortError) takes the early return.
    const gates = new Map<string, ReturnType<typeof deferred<Response>>>()
    installFetchStub((req) => {
      if (req.method === "GET" && req.url.startsWith("/api/v1/traces/")) {
        const traceId = decodeURIComponent(req.url.split("/").pop() ?? "")
        const gate = deferred<Response>()
        gates.set(traceId, gate)
        req.signal?.addEventListener("abort", () => {
          gate.reject(new DOMException("aborted", "AbortError"))
        })
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

    // Reselecting aborts the first request; its rejection must stay silent
    // and must never populate the detail for the new selection.
    act(() => {
      result.current.openTrace(ERROR_TRACE_ID)
    })
    await waitFor(() => {
      expect(gates.has(ERROR_TRACE_ID)).toBe(true)
    })
    expect(result.current.detail).toBeNull()
    expect(result.current.selectedTraceId).toBe(ERROR_TRACE_ID)

    await act(async () => {
      gates.get(ERROR_TRACE_ID)?.resolve(ok(errorTraceDetailFixture()))
    })
    await waitFor(() => {
      expect(result.current.detailStatus).toBe("ready")
    })
    expect(result.current.detail?.traceId).toBe(ERROR_TRACE_ID)
  })

  it("drops a late detail response that resolves after reselecting another trace", async () => {
    // Resolving-after-abort transport: unlike a real fetch (which rejects on
    // abort), this stub ignores the abort and resolves late, so only the
    // controller's post-await aborted guard can drop the stale payload.
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

    // Reselecting aborts the first request; its late resolution must never
    // publish the old trace into the new selection's dialog.
    act(() => {
      result.current.openTrace(ERROR_TRACE_ID)
    })
    await waitFor(() => {
      expect(gates.has(ERROR_TRACE_ID)).toBe(true)
    })
    expect(result.current.selectedTraceId).toBe(ERROR_TRACE_ID)

    await act(async () => {
      gates.get(SUCCESS_TRACE_ID)?.resolve(ok(traceDetailFixture()))
    })
    expect(result.current.detail).toBeNull()
    expect(result.current.detailStatus).toBe("loading")

    await act(async () => {
      gates.get(ERROR_TRACE_ID)?.resolve(ok(errorTraceDetailFixture()))
    })
    await waitFor(() => {
      expect(result.current.detailStatus).toBe("ready")
    })
    expect(result.current.detail?.traceId).toBe(ERROR_TRACE_ID)
  })

  it("surfaces detail errors and retries the same trace", async () => {
    let calls = 0
    stubTraces({
      detailHandler: () => {
        calls += 1
        return calls === 1
          ? err(404, { detail: "unknown trace" })
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
      expect(result.current.detailStatus).toBe("error")
    })
    expect(result.current.detailError).toContain("unknown trace")

    act(() => {
      result.current.retryDetail()
    })
    await waitFor(() => {
      expect(result.current.detailStatus).toBe("ready")
    })
    expect(result.current.detail?.traceId).toBe(SUCCESS_TRACE_ID)
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
