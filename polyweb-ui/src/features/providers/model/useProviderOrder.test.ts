import { act, renderHook } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { useProviderOrder } from "./useProviderOrder"

const mocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }))
vi.mock("@/domains/routing", () => ({ getProjectOrder: mocks.get, putProjectOrder: mocks.put }))
vi.mock("@/shared/notifications/useNotifications", () => ({ useNotifications: () => ({ showToast: vi.fn() }) }))

afterEach(() => vi.useRealTimers())

describe("useProviderOrder", () => {
  it("expires Undo after ten seconds", async () => {
    vi.useFakeTimers()
    const operation = { strategy: "lowest_cost", providers: [], notAllowed: [], hasSavedCustom: false }
    const data = { revision: 1, search: operation, fetch: operation }
    mocks.get.mockResolvedValue(data)
    mocks.put.mockResolvedValue(data)
    const { result } = renderHook(() => useProviderOrder("project"))
    await act(async () => { await Promise.resolve() })
    await act(async () => { await result.current.save("search", { strategy: "free_first" }, "lowest_cost") })
    expect(result.current.undo).toEqual({ operation: "search", strategy: "lowest_cost" })
    act(() => vi.advanceTimersByTime(9999))
    expect(result.current.undo).not.toBeNull()
    act(() => vi.advanceTimersByTime(1))
    expect(result.current.undo).toBeNull()
  })
})
