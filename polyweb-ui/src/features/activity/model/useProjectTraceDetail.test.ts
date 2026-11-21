import { beforeEach, describe, expect, it, vi } from "vitest"
import { act, renderHook, waitFor } from "@testing-library/react"
import {
  TRACE_NOT_IN_PROJECT_MESSAGE,
  TRACE_NOT_RECORDED_MESSAGE,
  TRACE_NOT_SAVED_MESSAGE,
  mapTraceDetail,
  type TraceDetail,
} from "@/domains/activity"
import { ApiError } from "@/shared/api/http"
import { SUCCESS_TRACE_ID, traceDetailFixture } from "@/test/backendFixtures"
import {
  TRACE_READ_NOT_PERMITTED_MESSAGE,
  useProjectTraceDetail,
  type ProjectTraceRequest,
} from "./useProjectTraceDetail"

const getProjectTrace = vi.hoisted(() => vi.fn())
vi.mock("@/domains/activity", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/domains/activity")>()),
  getProjectTrace,
}))

const PROJECT_ID = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
const OTHER_TRACE_ID = "b".repeat(32)

function detail(traceId: string): TraceDetail {
  return mapTraceDetail(traceDetailFixture({ trace_id: traceId }))
}

function request(overrides: Partial<ProjectTraceRequest> = {}): ProjectTraceRequest {
  return { projectId: PROJECT_ID, traceId: SUCCESS_TRACE_ID, canReadTraces: true, ...overrides }
}

beforeEach(() => {
  getProjectTrace.mockReset()
})

/**
 * The Playground's trace read: one project-scoped read per trace id, a
 * `missing` explanation (and no read) when there is nothing to read, and a
 * retry after a failed read. Review finding B3 on PR #77.
 */
describe("useProjectTraceDetail", () => {
  it.each([
    ["not_recorded", TRACE_NOT_RECORDED_MESSAGE],
    ["not_saved", TRACE_NOT_SAVED_MESSAGE],
  ] as const)("explains a %s trace without any read", (reason, message) => {
    const { result } = renderHook(() => useProjectTraceDetail(request({ traceId: null, reason })))
    expect(result.current).toMatchObject({ status: "missing", detail: null, error: message })
    expect(getProjectTrace).not.toHaveBeenCalled()
  })

  it("explains missing traces.read without any read", () => {
    const { result } = renderHook(() => useProjectTraceDetail(request({ canReadTraces: false })))
    expect(result.current).toMatchObject({ status: "missing", error: TRACE_READ_NOT_PERMITTED_MESSAGE })
    expect(getProjectTrace).not.toHaveBeenCalled()
  })

  it("reads the trace through the project route once", async () => {
    getProjectTrace.mockResolvedValue(detail(SUCCESS_TRACE_ID))
    const { result } = renderHook(() => useProjectTraceDetail(request()))
    expect(result.current.status).toBe("loading")

    await waitFor(() => expect(result.current.status).toBe("ready"))
    expect(result.current.detail?.traceId).toBe(SUCCESS_TRACE_ID)
    expect(getProjectTrace).toHaveBeenCalledTimes(1)
    expect(getProjectTrace).toHaveBeenCalledWith(PROJECT_ID, SUCCESS_TRACE_ID, expect.any(AbortSignal))
  })

  it("maps the project's 404 to missing", async () => {
    getProjectTrace.mockRejectedValue(new ApiError(404, "no trace", null))
    const { result } = renderHook(() => useProjectTraceDetail(request()))
    await waitFor(() => expect(result.current.status).toBe("missing"))
    expect(result.current.error).toBe(TRACE_NOT_IN_PROJECT_MESSAGE)
  })

  it("shows an error, then reads again on retry", async () => {
    getProjectTrace
      .mockRejectedValueOnce(new ApiError(503, "trace store down", null))
      .mockResolvedValueOnce(detail(SUCCESS_TRACE_ID))
    const { result } = renderHook(() => useProjectTraceDetail(request()))
    await waitFor(() => expect(result.current.status).toBe("error"))
    expect(result.current.error).toContain("trace store down")

    act(() => result.current.retry())

    await waitFor(() => expect(result.current.status).toBe("ready"))
    expect(getProjectTrace).toHaveBeenCalledTimes(2)
  })

  it("discards a late answer for a trace that is no longer requested", async () => {
    let resolveFirst: (value: TraceDetail) => void = () => {}
    getProjectTrace
      .mockImplementationOnce(() => new Promise<TraceDetail>((resolve) => { resolveFirst = resolve }))
      .mockResolvedValueOnce(detail(OTHER_TRACE_ID))
    const { result, rerender } = renderHook((props: ProjectTraceRequest) => useProjectTraceDetail(props), {
      initialProps: request(),
    })

    rerender(request({ traceId: OTHER_TRACE_ID }))
    await waitFor(() => expect(result.current.detail?.traceId).toBe(OTHER_TRACE_ID))

    await act(async () => {
      resolveFirst(detail(SUCCESS_TRACE_ID))
    })
    expect(result.current.detail?.traceId).toBe(OTHER_TRACE_ID)
  })
})
