import { describe, it, expect, afterEach, vi } from "vitest"
import { getProjectTrace, isTraceNotFound, listProjectTraces } from "./activityApi"
import { ApiError } from "@/shared/api/http"
import { installFetchStub, ok, err } from "@/test/fetchMock"
import { PROJECT_ALPHA_ID } from "@/test/accessFixtures"
import { SUCCESS_TRACE_ID, traceDetailFixture, traceListFixture } from "@/test/backendFixtures"

const TRACES = `/api/v1/projects/${PROJECT_ALPHA_ID}/traces`

/**
 * Project trace read API: the Activity list stays summary-only while detail
 * carries the disclosed query, results, and stage timeline. Exact relative
 * project URLs, query encoding, AbortSignal forwarding, and 404/error mapping.
 */
describe("activityApi project traces", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("listProjectTraces() GETs the project route with no query by default", async () => {
    const stub = installFetchStub(() => ok(traceListFixture({ next_cursor: "next-page" })))

    const page = await listProjectTraces(PROJECT_ALPHA_ID)

    expect(stub.requests).toHaveLength(1)
    expect(stub.requests[0]?.url).toBe(TRACES)
    expect(stub.requests[0]?.method).toBe("GET")
    expect(stub.requests[0]?.bodyText).toBeUndefined()
    expect(page.items).toHaveLength(3)
    expect(page.nextCursor).toBe("next-page")
  })

  it("listProjectTraces() encodes limit/operation/outcome/cursor as query params", async () => {
    const stub = installFetchStub(() => ok(traceListFixture()))

    const page = await listProjectTraces(PROJECT_ALPHA_ID, {
      limit: 50,
      operation: "fetch",
      outcome: "error",
      cursor: "opaque/cursor=",
    })

    expect(stub.requests[0]?.url).toBe(
      `${TRACES}?limit=50&operation=fetch&outcome=error&cursor=opaque%2Fcursor%3D`
    )
    expect(page.nextCursor).toBeNull()
  })

  it("listProjectTraces() forwards the AbortSignal", async () => {
    const stub = installFetchStub(() => ok(traceListFixture()))
    const controller = new AbortController()

    await listProjectTraces(PROJECT_ALPHA_ID, { limit: 10 }, controller.signal)

    expect(stub.requests[0]?.url).toBe(`${TRACES}?limit=10`)
    expect(stub.requests[0]?.signal).toBe(controller.signal)
  })

  it("getProjectTrace() GETs and decodes the project detail path", async () => {
    const stub = installFetchStub(() => ok(traceDetailFixture()))

    const detail = await getProjectTrace(PROJECT_ALPHA_ID, SUCCESS_TRACE_ID)

    expect(stub.requests[0]?.url).toBe(`${TRACES}/${SUCCESS_TRACE_ID}`)
    expect(detail.traceId).toBe(SUCCESS_TRACE_ID)
  })

  it("getProjectTrace() encodes hostile trace ids instead of building path segments", async () => {
    const stub = installFetchStub(() => ok(traceDetailFixture()))

    await getProjectTrace(PROJECT_ALPHA_ID, "a/b?c=d&e=f")

    expect(stub.requests[0]?.url).toBe(`${TRACES}/${encodeURIComponent("a/b?c=d&e=f")}`)
    expect(stub.requests[0]?.url).not.toContain("?")
  })

  it("maps a 404 of a foreign or unknown trace to isTraceNotFound", async () => {
    installFetchStub(() => err(404, { detail: "no trace for 'deadbeef'" }))

    const failure = await getProjectTrace(PROJECT_ALPHA_ID, "deadbeef").then(
      () => null,
      (error: unknown) => error
    )

    expect(failure).toBeInstanceOf(ApiError)
    expect(isTraceNotFound(failure)).toBe(true)
    expect(isTraceNotFound(new ApiError(500, "boom", null))).toBe(false)
  })

  it("maps a 500 trace failure to ApiError", async () => {
    installFetchStub(() => err(500, { detail: "trace store unavailable" }))

    const failure = await listProjectTraces(PROJECT_ALPHA_ID).then(
      () => null,
      (error: unknown) => error as ApiError
    )

    expect(failure).toBeInstanceOf(ApiError)
    expect(failure?.status).toBe(500)
    expect(failure?.detail).toBe("trace store unavailable")
  })

  it("never calls an absolute backend host literal for trace routes", async () => {
    installFetchStub((req) =>
      req.url.includes("/traces/") ? ok(traceDetailFixture()) : ok(traceListFixture())
    )

    await listProjectTraces(PROJECT_ALPHA_ID, { limit: 50 })
    await getProjectTrace(PROJECT_ALPHA_ID, SUCCESS_TRACE_ID)

    const fetchMock = vi.mocked(globalThis.fetch)
    for (const call of fetchMock.mock.calls) {
      const url = String(call[0])
      expect(url).not.toContain("127.0.0.1")
      expect(url.startsWith("/")).toBe(true)
    }
  })
})
