import { act, renderHook } from "@testing-library/react"
import type { DragEvent } from "react"
import { describe, expect, it, vi } from "vitest"
import { useDragReorder } from "./useDragReorder"

function dragEvent() {
  return {
    dataTransfer: { setData: vi.fn(), effectAllowed: "", dropEffect: "" },
    preventDefault: vi.fn(),
  } as unknown as DragEvent
}

describe("useProviderPriorityDrag", () => {
  it("moves the source to the target and clears the drag state", () => {
    const move = vi.fn().mockResolvedValue(undefined)
    const { result } = renderHook(() => useDragReorder(move))
    const event = dragEvent()
    act(() => result.current.startDrag("brave", event))
    act(() => result.current.dragOver("exa", event))
    expect(result.current.targetId).toBe("exa")
    act(() => result.current.drop("exa", event))
    expect(move).toHaveBeenCalledWith("brave", "exa")
    expect(result.current.draggingId).toBeNull()
    expect(result.current.targetId).toBeNull()
  })

  it("does not move a provider onto itself", () => {
    const move = vi.fn().mockResolvedValue(undefined)
    const { result } = renderHook(() => useDragReorder(move))
    const event = dragEvent()
    act(() => result.current.startDrag("brave", event))
    act(() => result.current.drop("brave", event))
    expect(move).not.toHaveBeenCalled()
    expect(result.current.draggingId).toBeNull()
  })
})
