import { act, renderHook } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import type { ProviderLimits } from "@/domains/dashboard"
import { apiService } from "@/services/api/freesearchApi"
import { useProviderLimits } from "./useProviderLimits"

const limits: ProviderLimits = {
  provider: "sample", active_auth_mode: "keyed", auths: [], documented_keyless_operations: [],
  version: 1, generated_at: "2026-11-08T10:00:00Z",
}

function controller() {
  const refreshDashboard = vi.fn(() => Promise.resolve())
  return { refreshDashboard, ...renderHook(() => useProviderLimits({
    providerId: "sample", limits, refreshDashboard, historyOpen: false,
  })) }
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe("useProviderLimits refresh outcomes", () => {
  it("never claims an update when a refresh joins a running lease", async () => {
    vi.spyOn(apiService, "syncProviderLimits").mockResolvedValue({ status: "skipped", reason: "lease_held" })
    const { result } = controller()
    await act(() => result.current.syncNow())
    expect(result.current.syncNote).toBe("Refresh already in progress")
    expect(result.current.updatedAt).toBeNull()
    expect(result.current.syncing).toBe(false)
  })

  it("records an update only after the provider and dashboard reads complete", async () => {
    vi.spyOn(apiService, "syncProviderLimits").mockResolvedValue({ status: "synced" })
    const { result, refreshDashboard } = controller()
    await act(() => result.current.syncNow())
    expect(result.current.updatedAt).toEqual(expect.any(Number))
    expect(refreshDashboard).toHaveBeenCalledOnce()
    expect(result.current.syncing).toBe(false)
  })

  it("resolves a hung refresh with a timeout and no update time", async () => {
    vi.useFakeTimers()
    vi.spyOn(apiService, "syncProviderLimits").mockImplementation(() => new Promise(() => {}))
    const { result } = controller()
    await act(async () => {
      const pending = result.current.syncNow()
      await vi.advanceTimersByTimeAsync(20_001)
      await pending
    })
    expect(result.current.syncing).toBe(false)
    expect(result.current.updatedAt).toBeNull()
    expect(result.current.syncNote).toBe("Refresh failed")
  })
})
