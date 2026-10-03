import { describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
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
  it("renders every span once in wire order with stable depth", () => {
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
    expect(rows).toHaveLength(detail.stages.length)
    expect(rows[0]).toHaveTextContent(/search request/i)
  })

  it("indents children by depth without nested disclosure boxes", () => {
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
    expect(document.querySelector("details")).toBeNull()
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
    const rows = within(list).getAllByRole("button")
    for (const row of rows) {
      expect(row.querySelector('span[style*="left"]')).not.toBeNull()
      expect(row.textContent).toMatch(/\d+ms/)
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
