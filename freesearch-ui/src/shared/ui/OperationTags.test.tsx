import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { OperationTags } from "./OperationTags"

describe("OperationTags", () => {
  it("renders one mono tag per operation", () => {
    render(<OperationTags operations={["search", "fetch"]} />)
    expect(screen.getByText("search")).toBeInTheDocument()
    expect(screen.getByText("fetch")).toBeInTheDocument()
    expect(screen.getByText("search").className).toContain("font-mono")
  })

  it("renders a muted dash when the list is empty", () => {
    const { container } = render(<OperationTags operations={[]} />)
    expect(container.textContent).toBe("—")
  })
})
