import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { StopOperationConfirm } from "./StopOperationConfirm"

describe("StopOperationConfirm", () => {
  it("identifies the operation and only says the other operation stays on when applicable", () => {
    const props = { provider: "exa", operation: "search" as const, projectName: "this project",
      pending: false, onClose: vi.fn(), onConfirm: vi.fn() }
    const { rerender } = render(<StopOperationConfirm {...props} remaining="fetch" />)
    expect(screen.getByRole("dialog", { name: "Stop Exa Search" })).toHaveTextContent(
      "Exa leaves the Search order of this project. Fetch stays on"
    )
    rerender(<StopOperationConfirm {...props} />)
    expect(screen.getByRole("dialog")).not.toHaveTextContent("stays on")
  })
})
