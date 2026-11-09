import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { renderHook, act } from "@testing-library/react"
import { useResultPreview } from "./useResultPreview"

/**
 * CLEANUP 2.4 consumer regression: the playground transient copy contract
 * must survive migration onto the shared clipboard hook unchanged —
 * unconditional 2s feedback, including on write failure.
 */

const clipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, "clipboard")

function mockClipboard(writeText: (text: string) => Promise<void>): void {
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
  })
}

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.restoreAllMocks()
  if (clipboardDescriptor) {
    Object.defineProperty(navigator, "clipboard", clipboardDescriptor)
  } else {
    Reflect.deleteProperty(navigator, "clipboard")
  }
  vi.useRealTimers()
})

describe("useResultPreview copyToClipboard", () => {
  it("marks copied and auto-resets after 2s on success", async () => {
    const writeText = vi.fn(() => Promise.resolve())
    mockClipboard(writeText)
    const { result } = renderHook(() => useResultPreview())

    expect(result.current.copied).toBe(false)
    act(() => {
      result.current.copyToClipboard("{\"hello\":\"world\"}")
    })
    await act(async () => {})
    expect(writeText).toHaveBeenCalledWith("{\"hello\":\"world\"}")
    expect(result.current.copied).toBe(true)

    act(() => {
      vi.advanceTimersByTime(2000)
    })
    expect(result.current.copied).toBe(false)
  })

  it("keeps the fire-and-forget quirk: copied stays set when the write rejects", async () => {
    mockClipboard(vi.fn(() => Promise.reject(new Error("denied"))))
    const { result } = renderHook(() => useResultPreview())

    let threw = false
    act(() => {
      try {
        result.current.copyToClipboard("payload")
      } catch {
        threw = true
      }
    })
    await act(async () => {})
    // Legacy behavior locked: rejection never surfaces and never clears the
    // flag (separate fix, not this slice).
    expect(threw).toBe(false)
    expect(result.current.copied).toBe(true)
    act(() => {
      vi.advanceTimersByTime(2000)
    })
    expect(result.current.copied).toBe(false)
  })

  it("does not throw when the Clipboard API is missing", async () => {
    Reflect.deleteProperty(navigator, "clipboard")
    const { result } = renderHook(() => useResultPreview())

    // Legacy threw a synchronous TypeError here; the shared hook normalizes
    // the missing-API path to a silent no-op (flag stays clear).
    act(() => {
      result.current.copyToClipboard("payload")
    })
    await act(async () => {})
    expect(result.current.copied).toBe(false)
  })
})
