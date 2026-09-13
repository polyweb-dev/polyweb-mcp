import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { renderHook, act } from "@testing-library/react"
import { useClipboard } from "./useClipboard"

/**
 * CLEANUP 2.4 characterization: shared clipboard hook covering BOTH legacy
 * modes — transient auto-reset (useResultPreview, 2000ms) and sticky
 * retention + availability/rejection silence (usePairingFlow.copyCode).
 */

const clipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, "clipboard")

function mockClipboard(writeText: (text: string) => Promise<void>): void {
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
  })
}

function restoreClipboard(): void {
  if (clipboardDescriptor) {
    Object.defineProperty(navigator, "clipboard", clipboardDescriptor)
  } else {
    Reflect.deleteProperty(navigator, "clipboard")
  }
}

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.restoreAllMocks()
  restoreClipboard()
  vi.useRealTimers()
})

describe("useClipboard transient mode", () => {
  it("reports success and auto-resets copied after the timeout", async () => {
    const writeText = vi.fn(() => Promise.resolve())
    mockClipboard(writeText)
    const { result } = renderHook(() => useClipboard({ resetAfterMs: 2000 }))

    let ok = false
    await act(async () => {
      ok = await result.current.copy("hello")
    })
    expect(ok).toBe(true)
    expect(writeText).toHaveBeenCalledWith("hello")
    expect(result.current.copied).toBe(true)

    act(() => {
      vi.advanceTimersByTime(1999)
    })
    expect(result.current.copied).toBe(true)
    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(result.current.copied).toBe(false)
  })

  it("restarts the reset timer on repeat copies", async () => {
    mockClipboard(vi.fn(() => Promise.resolve()))
    const { result } = renderHook(() => useClipboard({ resetAfterMs: 2000 }))

    await act(async () => {
      await result.current.copy("first")
    })
    act(() => {
      vi.advanceTimersByTime(1500)
    })
    await act(async () => {
      await result.current.copy("second")
    })
    // 1500ms after the second copy the flag must still hold: the second
    // copy restarted the window (legacy stacked timers cleared early here).
    act(() => {
      vi.advanceTimersByTime(1500)
    })
    expect(result.current.copied).toBe(true)
    act(() => {
      vi.advanceTimersByTime(500)
    })
    expect(result.current.copied).toBe(false)
  })

  it("preserves the legacy fire-and-forget quirk with optimistic feedback", async () => {
    // useResultPreview sets copied unconditionally and lets the write
    // promise float: rejection never clears the flag. optimistic: true
    // locks that quirk (the report still resolves false for future fixes).
    mockClipboard(vi.fn(() => Promise.reject(new Error("denied"))))
    const { result } = renderHook(() => useClipboard({ resetAfterMs: 2000, optimistic: true }))

    let ok = true
    await act(async () => {
      ok = await result.current.copy("hello")
    })
    expect(ok).toBe(false)
    expect(result.current.copied).toBe(true)
    act(() => {
      vi.advanceTimersByTime(2000)
    })
    expect(result.current.copied).toBe(false)
  })

  it("clears the pending reset timer on unmount", async () => {
    mockClipboard(vi.fn(() => Promise.resolve()))
    const clearSpy = vi.spyOn(globalThis, "clearTimeout")
    const { result, unmount } = renderHook(() => useClipboard({ resetAfterMs: 2000 }))

    await act(async () => {
      await result.current.copy("hello")
    })
    expect(result.current.copied).toBe(true)
    act(() => {
      unmount()
    })
    expect(clearSpy).toHaveBeenCalled()
    // Firing the orphaned timer must not touch state after unmount.
    act(() => {
      vi.advanceTimersByTime(5000)
    })
  })
})

describe("useClipboard sticky mode", () => {
  it("retains copied until an explicit reset", async () => {
    const writeText = vi.fn(() => Promise.resolve())
    mockClipboard(writeText)
    const { result } = renderHook(() => useClipboard())

    let ok = false
    await act(async () => {
      ok = await result.current.copy("ABCD-1234")
    })
    expect(ok).toBe(true)
    expect(writeText).toHaveBeenCalledWith("ABCD-1234")
    expect(result.current.copied).toBe(true)

    act(() => {
      vi.advanceTimersByTime(100_000)
    })
    expect(result.current.copied).toBe(true)

    act(() => {
      result.current.reset()
    })
    expect(result.current.copied).toBe(false)
  })

  it("swallows write rejection silently without touching the flag", async () => {
    mockClipboard(vi.fn(() => Promise.reject(new Error("denied"))))
    const { result } = renderHook(() => useClipboard())

    let ok = true
    await act(async () => {
      ok = await result.current.copy("ABCD-1234")
    })
    expect(ok).toBe(false)
    expect(result.current.copied).toBe(false)
  })

  it("no-ops when the Clipboard API is unavailable", async () => {
    restoreClipboard()
    Reflect.deleteProperty(navigator, "clipboard")
    const { result } = renderHook(() => useClipboard())

    let ok = true
    await act(async () => {
      ok = await result.current.copy("ABCD-1234")
    })
    expect(ok).toBe(false)
    expect(result.current.copied).toBe(false)
  })
})
