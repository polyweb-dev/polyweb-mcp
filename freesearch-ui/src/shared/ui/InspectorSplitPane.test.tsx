import { describe, expect, it } from "vitest"
import { render, screen, within } from "@testing-library/react"
import { InspectorSplitPane } from "./InspectorSplitPane"

/**
 * The neutral shared split shell (PLAN §6.3 item 8, §4.1). It owns geometry
 * only — two labelled regions, desktop 7fr/5fr grid with a 16–24px gap,
 * min-w-0 containment on both panes, a sticky side inspector, natural stacking
 * below `lg`, and no domain types, selection state, or payload interpretation.
 */
describe("InspectorSplitPane", () => {
  function renderPane() {
    return render(
      <InspectorSplitPane
        primaryLabel="Results"
        detailLabel="Inspector"
        primary={<p>Primary content</p>}
        detail={<p>Detail content</p>}
      />
    )
  }

  it("renders two labelled regions with their slots", () => {
    renderPane()

    const primary = screen.getByRole("region", { name: "Results" })
    const detail = screen.getByRole("region", { name: "Inspector" })
    expect(within(primary).getByText("Primary content")).toBeInTheDocument()
    expect(within(detail).getByText("Detail content")).toBeInTheDocument()
  })

  it("uses the shared 7fr/5fr desktop grid with a 16–24px gap", () => {
    const { container } = renderPane()

    const grid = container.firstElementChild as HTMLElement
    expect(grid.className).toMatch(/grid/)
    expect(grid.className).toMatch(/lg:grid-cols-\[minmax\(0,7fr\)_minmax\(20rem,5fr\)\]|7fr.*5fr/)
    expect(grid.className).toMatch(/gap-4|gap-5|gap-6|gap-\[16px\]|gap-\[20px\]|gap-\[24px\]/)
  })

  it("contains overflow in both panes and keeps the inspector sticky", () => {
    renderPane()

    const primary = screen.getByRole("region", { name: "Results" })
    const detail = screen.getByRole("region", { name: "Inspector" })
    expect(primary.className).toMatch(/min-w-0/)
    expect(detail.className).toMatch(/min-w-0/)
    expect(detail.className).toMatch(/lg:sticky/)
    expect(detail.className).toMatch(/lg:top-0/)
  })

  it("stacks naturally below lg without adding responsive policy", () => {
    const { container } = renderPane()

    const grid = container.firstElementChild as HTMLElement
    expect(grid.className).toMatch(/grid-cols-1/)
  })

  it("passes through an optional className without swallowing slots", () => {
    render(
      <InspectorSplitPane
        primaryLabel="Results"
        detailLabel="Inspector"
        primary={<p>Primary content</p>}
        detail={<p>Detail content</p>}
        className="test-shell"
      />
    )

    expect(document.querySelector(".test-shell")).not.toBeNull()
    expect(screen.getByText("Primary content")).toBeInTheDocument()
    expect(screen.getByText("Detail content")).toBeInTheDocument()
  })
})
