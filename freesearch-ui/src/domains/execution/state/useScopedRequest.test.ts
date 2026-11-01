import { describe, expect, it } from "vitest"
import { renderHook } from "@testing-library/react"
import { useScopedRequest } from "./useScopedRequest"

describe("useScopedRequest", () => {
  it("aborts the previous request when a new one begins", () => {
    const { result } = renderHook(() => useScopedRequest())
    const first = result.current.begin()
    const second = result.current.begin()
    expect(first.signal.aborted).toBe(true)
    expect(second.signal.aborted).toBe(false)
  })

  it("aborts the last request on unmount", () => {
    const { result, unmount } = renderHook(() => useScopedRequest())
    const controller = result.current.begin()
    unmount()
    expect(controller.signal.aborted).toBe(true)
  })

  it("forgets an ended request, so unmount aborts nothing that already settled", () => {
    const { result, unmount } = renderHook(() => useScopedRequest())
    const controller = result.current.begin()
    result.current.end(controller)
    unmount()
    expect(controller.signal.aborted).toBe(false)
  })

  it("ignores the end of a request that a newer one replaced", () => {
    const { result, unmount } = renderHook(() => useScopedRequest())
    const stale = result.current.begin()
    const current = result.current.begin()
    result.current.end(stale)
    unmount()
    expect(current.signal.aborted).toBe(true)
  })
})
