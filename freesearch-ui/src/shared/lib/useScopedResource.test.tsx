import { describe, expect, it, vi, afterEach } from "vitest"
import { act, renderHook } from "@testing-library/react"
import { useScopedResource } from "./useScopedResource"

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

describe("useScopedResource", () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it("loads the initial scope and exposes the data", async () => {
    const load = vi.fn(async (signal: AbortSignal) => {
      void signal
      return "alpha"
    })
    const { result } = renderHook(() => useScopedResource({ scopeKey: "a", load }))
    expect(result.current.status).toBe("loading")
    await act(async () => {})
    expect(result.current).toMatchObject({ status: "ready", data: "alpha" })
    expect(load).toHaveBeenCalledTimes(1)
  })

  it("aborts the in-flight request when the scope changes", async () => {
    const loads: Array<ReturnType<typeof deferred<string>>> = []
    const signals: AbortSignal[] = []
    const load = vi.fn((signal: AbortSignal) => {
      signals.push(signal)
      const next = deferred<string>()
      loads.push(next)
      return next.promise
    })
    const { result, rerender } = renderHook(
      ({ scopeKey }) => useScopedResource({ scopeKey, load }),
      { initialProps: { scopeKey: "a" } }
    )
    expect(signals).toHaveLength(1)
    rerender({ scopeKey: "b" })
    expect(signals[0]?.aborted).toBe(true)
    expect(result.current.status).toBe("loading")
    await act(async () => {
      loads[0]?.resolve("stale")
    })
    expect(result.current.status).toBe("loading")
    await act(async () => {
      loads[1]?.resolve("beta")
    })
    expect(result.current).toMatchObject({ status: "ready", data: "beta" })
  })

  it("ignores a late resolve of the old scope after the new scope is ready", async () => {
    const first = deferred<string>()
    const second = deferred<string>()
    const loads = [first, second]
    let call = 0
    const load = vi.fn((signal: AbortSignal) => {
      void signal
      const d = loads[call] ?? second
      call += 1
      return d.promise
    })
    const { result, rerender } = renderHook(
      ({ scopeKey }) => useScopedResource({ scopeKey, load }),
      { initialProps: { scopeKey: "a" } }
    )
    rerender({ scopeKey: "b" })
    await act(async () => {
      second.resolve("beta")
    })
    expect(result.current).toMatchObject({ status: "ready", data: "beta" })
    await act(async () => {
      first.resolve("stale-alpha")
    })
    expect(result.current).toMatchObject({ status: "ready", data: "beta" })
  })

  it("polls on the interval and stops after unmount", async () => {
    vi.useFakeTimers()
    const load = vi.fn(async (signal: AbortSignal) => {
      void signal
      return "tick"
    })
    const { result, unmount } = renderHook(() =>
      useScopedResource({ scopeKey: "a", load, pollMs: 1000 })
    )
    await act(async () => {})
    expect(load).toHaveBeenCalledTimes(1)
    await act(async () => {
      vi.advanceTimersByTime(2500)
    })
    expect(load).toHaveBeenCalledTimes(3)
    unmount()
    await act(async () => {
      vi.advanceTimersByTime(5000)
    })
    expect(load).toHaveBeenCalledTimes(3)
    expect(result.current.status).toBe("ready")
  })

  it("reload from a stale render or after unmount sends no request", async () => {
    const load = vi.fn(async (signal: AbortSignal) => {
      void signal
      return "v"
    })
    const { result, rerender, unmount } = renderHook(
      ({ scopeKey }) => useScopedResource({ scopeKey, load }),
      { initialProps: { scopeKey: "a" } }
    )
    await act(async () => {})
    const staleReload = result.current.reload
    rerender({ scopeKey: "b" })
    await act(async () => {})
    expect(load).toHaveBeenCalledTimes(2)
    await staleReload()
    expect(load).toHaveBeenCalledTimes(2)
    const liveReload = result.current.reload
    unmount()
    await liveReload()
    expect(load).toHaveBeenCalledTimes(2)
  })

  it("reload re-runs the load of the current scope", async () => {
    let call = 0
    const load = vi.fn(async (signal: AbortSignal) => {
      void signal
      call += 1
      return `value-${call}`
    })
    const { result } = renderHook(() => useScopedResource({ scopeKey: "a", load }))
    await act(async () => {})
    expect(result.current).toMatchObject({ status: "ready", data: "value-1" })
    await act(async () => {
      result.current.reload()
    })
    expect(result.current).toMatchObject({ status: "ready", data: "value-2" })
  })

  it("exposes the error state when the load rejects", async () => {
    const load = vi.fn(async (signal: AbortSignal) => {
      void signal
      throw new Error("boom")
    })
    const { result } = renderHook(() => useScopedResource({ scopeKey: "a", load }))
    await act(async () => {})
    expect(result.current.status).toBe("error")
  })
})
