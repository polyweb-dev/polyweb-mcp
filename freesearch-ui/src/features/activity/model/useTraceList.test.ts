import { afterEach, describe, expect, it, vi } from "vitest"
import { act, renderHook, waitFor } from "@testing-library/react"
import { useTraceList } from "./useTraceList"
import type { ActivityFilters } from "./activityFilters"
import { deferred, err, installFetchStub, ok } from "@/test/fetchMock"
import type { RecordedRequest } from "@/test/fetchMock"
import { PROJECT_ALPHA_ID } from "@/test/accessFixtures"
import { traceListFixture, traceSummaryFixture } from "@/test/fixtures/activity"

const TRACES = `/api/v1/projects/${PROJECT_ALPHA_ID}/traces`
const ALL: ActivityFilters = { operation: null, outcome: null }
const EXTRA_ID = "f".repeat(32)

function renderList(filters: ActivityFilters = ALL) {
  return renderHook(
    (props: { filters: ActivityFilters; token: number }) =>
      useTraceList(PROJECT_ALPHA_ID, props.filters, props.token),
    { initialProps: { filters, token: 0 } }
  )
}

/** Page one carries a cursor; the cursor page repeats one row and adds one. */
function pagedHandler(req: RecordedRequest): Response | Promise<Response> {
  if (!req.url.includes("cursor=")) return ok(traceListFixture({ next_cursor: "page-2" }))
  return ok({
    items: [traceSummaryFixture(), { ...traceSummaryFixture(), trace_id: EXTRA_ID }],
    generated_at: "2026-09-29T09:25:00.000000Z",
    next_cursor: null,
  })
}

describe("useTraceList", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("resets to page one and aborts the previous list when a filter changes", async () => {
    const gates: Array<ReturnType<typeof deferred<Response>>> = []
    const stub = installFetchStub(() => {
      const gate = deferred<Response>()
      gates.push(gate)
      return gate.promise
    })
    const { result, rerender } = renderList()
    await waitFor(() => expect(gates).toHaveLength(1))

    rerender({ filters: { operation: "fetch", outcome: "error" }, token: 0 })
    await waitFor(() => expect(gates).toHaveLength(2))
    expect(stub.requests[0]?.signal?.aborted).toBe(true)
    expect(stub.requests[1]?.url).toBe(`${TRACES}?limit=50&operation=fetch&outcome=error`)

    await act(async () => {
      gates[0]?.resolve(ok(traceListFixture()))
    })
    expect(result.current.listStatus).toBe("loading")
    await act(async () => {
      gates[1]?.resolve(ok(traceListFixture({ items: [traceSummaryFixture()] })))
    })
    await waitFor(() => expect(result.current.listStatus).toBe("ready"))
    expect(result.current.summaries).toHaveLength(1)
  })

  it("appends the cursor page on loadMore and skips a row it already holds", async () => {
    installFetchStub(pagedHandler)
    const { result } = renderList()
    await waitFor(() => expect(result.current.hasMore).toBe(true))
    expect(result.current.summaries).toHaveLength(3)

    act(() => result.current.loadMore())
    await waitFor(() => expect(result.current.summaries).toHaveLength(4))
    expect(result.current.summaries[3]?.traceId).toBe(EXTRA_ID)
    expect(result.current.hasMore).toBe(false)
    expect(result.current.moreStatus).toBe("idle")
  })

  it("drops a Load more page that resolves after a filter change", async () => {
    const more = deferred<Response>()
    const stub = installFetchStub((req) =>
      req.url.includes("cursor=") ? more.promise : pagedHandler(req)
    )
    const { result, rerender } = renderList()
    await waitFor(() => expect(result.current.hasMore).toBe(true))
    act(() => result.current.loadMore())
    await waitFor(() => expect(result.current.moreStatus).toBe("loading"))
    const moreRequest = stub.requests.find((req) => req.url.includes("cursor="))

    rerender({ filters: { operation: "search", outcome: null }, token: 0 })
    expect(moreRequest?.signal?.aborted).toBe(true)
    await waitFor(() => expect(result.current.listStatus).toBe("ready"))

    await act(async () => {
      more.resolve(
        ok({ items: [{ ...traceSummaryFixture(), trace_id: EXTRA_ID }], generated_at: "x", next_cursor: null })
      )
    })
    expect(result.current.summaries.some((row) => row.traceId === EXTRA_ID)).toBe(false)
    expect(result.current.hasMore).toBe(true)
  })

  it("shows the error state on a timeout instead of loading forever", async () => {
    installFetchStub(() =>
      Promise.reject(new DOMException("The operation was aborted due to timeout", "TimeoutError"))
    )
    const { result } = renderList()

    await waitFor(() => expect(result.current.listStatus).toBe("error"))
    expect(result.current.listError).toMatch(/timed out/i)
  })

  it("shows a Load more failure, including a timeout, and keeps the loaded rows", async () => {
    installFetchStub((req) =>
      req.url.includes("cursor=")
        ? Promise.reject(new DOMException("The operation was aborted due to timeout", "TimeoutError"))
        : pagedHandler(req)
    )
    const { result } = renderList()
    await waitFor(() => expect(result.current.hasMore).toBe(true))

    act(() => result.current.loadMore())
    await waitFor(() => expect(result.current.moreStatus).toBe("error"))
    expect(result.current.moreError).toMatch(/timed out/i)
    expect(result.current.summaries).toHaveLength(3)
  })

  it("reloads page one when the refresh token changes", async () => {
    let calls = 0
    installFetchStub(() => {
      calls += 1
      return calls === 1 ? err(503, { detail: "down" }) : ok(traceListFixture())
    })
    const { result, rerender } = renderList()
    await waitFor(() => expect(result.current.listStatus).toBe("error"))

    rerender({ filters: ALL, token: 1 })
    await waitFor(() => expect(result.current.listStatus).toBe("ready"))
    expect(result.current.summaries).toHaveLength(3)
  })
})
