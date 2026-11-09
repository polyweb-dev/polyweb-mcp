import { describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { selectUserTraceStages } from "@/domains/activity/model/tracePresentation"
import { mapTraceDetail } from "@/domains/activity/model/mappers"
import {
  aggregatedTraceDetailFixture,
  errorTraceDetailFixture,
} from "@/test/fixtures/activity"
import { TraceTrajectory } from "./TraceTrajectory"

/**
 * The fused trajectory list (PLAN §6.3 item 7): one row per span in wire order,
 * depth indentation, one shared-scale offset/duration bar fused into every row,
 * provider labels from `stage.providerId`, failed status, selected-row
 * treatment, and an `onSelect(spanId)` handoff for the side payload. It replaces
 * the nested-disclosure timeline (`TraceTimeline.test.tsx` is deleted).
 */
describe("TraceTrajectory", () => {
  it("names the route step Provider selection", () => {
    const detail = mapTraceDetail(aggregatedTraceDetailFixture())
    const stages = detail.stages.map((stage, index) => index === 0 ? { ...stage, label: "Route selection" } : stage)
    render(<TraceTrajectory stages={stages} totalMs={detail.totalMs} selectedSpanId={null} onSelect={vi.fn()} />)
    expect(screen.getByText("Provider selection")).toBeInTheDocument()
    expect(screen.queryByText("Route selection")).not.toBeInTheDocument()
  })
  it("renders user-level stages once in canonical order with stable depth", () => {
    const detail = mapTraceDetail(aggregatedTraceDetailFixture())
    const visible = selectUserTraceStages(detail.stages)
    render(
      <TraceTrajectory
        stages={detail.stages}
        totalMs={detail.totalMs}
        selectedSpanId={null}
        onSelect={() => {}}
      />
    )

    const list = screen.getByRole("list", { name: /trajectory/i })
    const rows = within(list).getAllByRole("button").filter((row) => row.hasAttribute("data-depth"))
    expect(visible).toHaveLength(11)
    expect(rows).toHaveLength(visible.length)
    expect(rows[0]).toHaveTextContent(/search request/i)
    expect(within(list).queryByText(/provider http call/i)).not.toBeInTheDocument()
    expect(within(list).queryByText(/provider response parse/i)).not.toBeInTheDocument()
    expect(within(list).getAllByTestId(/provider-logo-/)).toHaveLength(7)
    expect(screen.queryByRole("button", { name: /^provider request$/i })).not.toBeInTheDocument()
  })

  it("fills its pane with one scroll region instead of a fixed cap", () => {
    const detail = mapTraceDetail(aggregatedTraceDetailFixture())
    const { container } = render(
      <TraceTrajectory
        stages={detail.stages}
        totalMs={detail.totalMs}
        selectedSpanId={null}
        onSelect={() => {}}
      />
    )

    const root = container.firstElementChild as HTMLElement
    expect(root.className).toMatch(/flex-col/)
    expect(root.className).toMatch(/h-full/)

    const scroller = root.lastElementChild as HTMLElement
    expect(scroller.className).toMatch(/flex-1/)
    expect(scroller.className).toMatch(/overflow-y-auto/)
    expect(scroller.className).toMatch(/min-h-\[4rem\]/)
    // The pane above owns the height now; a fixed cap would fight it.
    expect(scroller.className).not.toMatch(/max-h-\[/)
    expect(within(scroller).getByRole("list", { name: "Trace trajectory" })).toBeInTheDocument()
  })

  it("keeps only comparable user-level stages in the waterfall", () => {
    const detail = mapTraceDetail(aggregatedTraceDetailFixture())
    render(
      <TraceTrajectory
        stages={detail.stages}
        totalMs={detail.totalMs}
        selectedSpanId={null}
        onSelect={() => {}}
      />
    )

    const list = screen.getByRole("list", { name: /trajectory/i })
    const rows = within(list).getAllByRole("button")
    const depths = rows.map((row) => row.getAttribute("data-depth") ?? row.getAttribute("aria-level"))
    expect(depths[0]).not.toBe(depths[1])
    expect(within(list).queryByRole("button", { name: /HTTP request|Response parsing/ })).not.toBeInTheDocument()
    expect(within(list).queryByText(/Provider steps|Other recorded steps|Recorded substeps/)).not.toBeInTheDocument()
  })

  it("fuses one shared-scale offset/duration bar into every row", () => {
    const detail = mapTraceDetail(aggregatedTraceDetailFixture())
    render(
      <TraceTrajectory
        stages={detail.stages}
        totalMs={detail.totalMs}
        selectedSpanId={null}
        onSelect={() => {}}
      />
    )

    const list = screen.getByRole("list", { name: /trajectory/i })
    const rows = within(list).getAllByRole("button").filter((row) => row.hasAttribute("data-depth"))
    for (const row of rows) {
      expect(row.querySelector('span[style*="left"]')).not.toBeNull()
      expect(row.textContent).toMatch(/[\d,]+ ms/)
      expect(row.textContent).not.toMatch(/\d+ res/)
    }
  })

  it("labels provider spans from the direct provider field", () => {
    const detail = mapTraceDetail(aggregatedTraceDetailFixture())
    render(
      <TraceTrajectory
        stages={detail.stages}
        totalMs={detail.totalMs}
        selectedSpanId={null}
        onSelect={() => {}}
      />
    )

    expect(screen.getByRole("button", { name: /keenable request/i })).toBeInTheDocument()
    expect(screen.getByTitle("Keenable request")).toHaveClass("whitespace-nowrap", "overflow-hidden")
    expect(screen.getByRole("button", { name: /parallel request/i })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /^provider request$/i })).not.toBeInTheDocument()
  })

  it("keeps the failed attempt outcome visible in its row", () => {
    const detail = mapTraceDetail(errorTraceDetailFixture())
    render(
      <TraceTrajectory
        stages={detail.stages}
        totalMs={detail.totalMs}
        selectedSpanId={null}
        onSelect={() => {}}
      />
    )

    const failed = screen.getByRole("button", { name: /provider request/i })
    expect(failed).toHaveTextContent(/error/i)
  })

  it("summarizes provider time as the interval union, not the duration sum", () => {
    const detail = mapTraceDetail(aggregatedTraceDetailFixture())
    render(
      <TraceTrajectory
        stages={detail.stages}
        totalMs={detail.totalMs}
        selectedSpanId={null}
        onSelect={() => {}}
      />
    )

    const active = screen.getByText("Provider active").closest("div")!
    const activeMs = Number((active.textContent ?? "").replace(/[^0-9]/g, ""))
    const durationSum = detail.stages
      .filter((stage) => stage.name === "freesearch.provider")
      .reduce((sum, stage) => sum + stage.durationMs, 0)
    expect(activeMs).toBeGreaterThan(0)
    expect(activeMs).toBeLessThan(durationSum)
    expect(screen.queryByText("Outside provider calls")).not.toBeInTheDocument()
  })

  it("carries the inset focus ring on trajectory rows and the ms unit outside the axis", () => {
    const detail = mapTraceDetail(aggregatedTraceDetailFixture())
    render(
      <TraceTrajectory
        stages={detail.stages}
        totalMs={detail.totalMs}
        selectedSpanId={null}
        onSelect={() => {}}
      />
    )

    // Item 5: the inset ring survives the trajectory scroll container, the
    // ruler ticks stay bare numbers, and the millisecond unit sits outside
    // the track so the final tick can never wrap or clip.
    const row = screen.getByRole("button", { name: /keenable request/i })
    expect(row.className).toContain("focus-visible:ring-inset")
    expect(row.className).toContain("focus-visible:ring-2")
    // The compact ruler ticks sit at round values (0 / 2,000 for 3,381 ms).
    for (const tick of ["0", "2,000"]) expect(screen.getByText(tick)).toBeInTheDocument()
    expect(screen.queryByText(String(detail.totalMs))).not.toBeInTheDocument()
    expect(screen.getByText("ms")).toBeInTheDocument()
    expect(within(screen.getByRole("list", { name: /trajectory/i })).getByText("3,381 ms")).toBeInTheDocument()
  })

  it("marks the selected row and hands its span id to the side payload", async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    const detail = mapTraceDetail(aggregatedTraceDetailFixture())
    render(
      <TraceTrajectory
        stages={detail.stages}
        totalMs={detail.totalMs}
        selectedSpanId="a100000000000003"
        onSelect={onSelect}
      />
    )

    const selected = screen.getByRole("button", { name: /keenable request/i })
    expect(selected).toHaveAttribute("aria-pressed", "true")

    await user.click(screen.getByRole("button", { name: /tavily request/i }))
    expect(onSelect).toHaveBeenCalledWith("a100000000000006")

    selected.focus()
    await user.keyboard("{Enter}")
    expect(onSelect).toHaveBeenCalledWith("a100000000000003")
  })
})
