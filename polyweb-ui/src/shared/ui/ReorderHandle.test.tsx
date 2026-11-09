import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { ReorderHandle } from "./ReorderHandle"

describe("PriorityIndicator", () => {
  it("retains drag and arrow controls for project order", () => {
    const move = vi.fn()
    render(
      <ReorderHandle
        label="Brave Search"
        rank={1}
        count={2}
        canEdit
        pending={false}
        onDragStart={vi.fn()}
        onDragEnd={vi.fn()}
        onMove={move}
      />,
    )
    expect(screen.getByRole("img", { name: "Drag Brave Search to change priority" })).toHaveAttribute("draggable", "true")
    expect(screen.getByRole("button", { name: "Move Brave Search priority up" })).toBeDisabled()
    fireEvent.click(screen.getByRole("button", { name: "Move Brave Search priority down" }))
    expect(move).toHaveBeenCalledWith("down")
  })
})
