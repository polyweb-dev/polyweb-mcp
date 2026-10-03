import { describe, expect, it } from "vitest"
import { render, screen, within } from "@testing-library/react"
import { mapTraceDetail } from "@/domains/activity"
import type { TraceStage } from "@/domains/activity"
import { TraceTimeline } from "./TraceTimeline"
import { errorTraceDetailFixture, traceDetailFixture } from "@/test/fixtures/activity"

/**
 * The stage timeline renders one row per span in trace order, each with its
 * own duration. Concurrent provider spans share an offset branch instead of
 * pretending to be sequential; failed stages carry their error inline.
 */
describe("TraceTimeline", () => {
  it("renders stages in order with per-stage durations", () => {
    const detail = mapTraceDetail(traceDetailFixture())
    render(<TraceTimeline stages={detail.stages} totalMs={detail.totalMs} />)

    const timeline = screen.getByRole("list", { name: "Stage timeline" })
    const items = within(timeline).getAllByRole("listitem")
    expect(items).toHaveLength(7)
    expect(items[0]).toHaveTextContent("Search request")
    expect(items[0]).toHaveTextContent("248ms")
    expect(items[3]).toHaveTextContent("Provider HTTP call")
    expect(items[3]).toHaveTextContent("202ms")

    const labels = items.map((item) => item.textContent)
    expect(labels.join("\n")).toMatch(/Search request.*Backend handling/s)
  })

  it("renders parallel provider spans as overlapping branches", () => {
    const stages: TraceStage[] = [
      {
        spanId: "aabbccddeeff0011",
        parentSpanId: null,
        name: "POST /search",
        label: "Search request",
        kind: "server",
        startedAt: "2026-09-29T09:15:00.000000Z",
        durationMs: 200,
        offsetMs: 0,
        outcome: "partial",
        error: null,
        events: [],
      },
      {
        spanId: "aabbccddeeff0022",
        parentSpanId: "aabbccddeeff0011",
        name: "freesearch.provider",
        label: "Provider request",
        kind: "client",
        startedAt: "2026-09-29T09:15:00.010000Z",
        durationMs: 150,
        offsetMs: 10,
        outcome: "success",
        error: null,
        events: [],
      },
      {
        spanId: "aabbccddeeff0033",
        parentSpanId: "aabbccddeeff0011",
        name: "freesearch.provider",
        label: "Provider request",
        kind: "client",
        startedAt: "2026-09-29T09:15:00.012000Z",
        durationMs: 150,
        offsetMs: 12,
        outcome: "error",
        error: { type: "http_error", message: "HTTP 502" },
        events: [],
      },
    ]
    render(<TraceTimeline stages={stages} totalMs={200} />)

    const items = screen.getAllByRole("listitem")
    expect(items).toHaveLength(3)
    // Both provider branches render side by side in trace order, not merged.
    expect(items[1]).toHaveTextContent("Provider request")
    expect(items[2]).toHaveTextContent("Provider request")
    expect(items[2]).toHaveTextContent("http_error: HTTP 502")
  })

  it("marks failed stages with error pills and messages", () => {
    const detail = mapTraceDetail(errorTraceDetailFixture())
    render(<TraceTimeline stages={detail.stages} totalMs={detail.totalMs} />)

    const items = screen.getAllByRole("listitem")
    expect(items).toHaveLength(2)
    expect(items[1]).toHaveTextContent("494ms")
    expect(items[1]).toHaveTextContent("error")
    expect(items[1]).toHaveTextContent("http_error: HTTP 502")
  })

  it("shows successful stages without error pills", () => {
    const detail = mapTraceDetail(traceDetailFixture())
    render(<TraceTimeline stages={detail.stages} totalMs={detail.totalMs} />)

    expect(screen.queryByText(/http_error/i)).not.toBeInTheDocument()
    expect(screen.getByText("Backend handling")).toBeInTheDocument()
  })

  it("renders an empty state when no stages were recorded", () => {
    render(<TraceTimeline stages={[]} totalMs={1} />)

    expect(screen.getByText(/no stage timing was recorded/i)).toBeInTheDocument()
    expect(screen.queryByRole("list")).not.toBeInTheDocument()
  })

  it("stays collapsed until the timeline disclosure is opened", () => {
    const detail = mapTraceDetail(traceDetailFixture())
    const { rerender } = render(
      <details>
        <summary>Stage timeline</summary>
        <TraceTimeline stages={detail.stages} totalMs={detail.totalMs} />
      </details>
    )

    // Collapsed by default; opened disclosures render the full timeline.
    expect(screen.getByText("Stage timeline").closest("details")).not.toHaveAttribute(
      "open"
    )
    rerender(
      <details open>
        <summary>Stage timeline</summary>
        <TraceTimeline stages={detail.stages} totalMs={detail.totalMs} />
      </details>
    )
    expect(screen.getByRole("list", { name: "Stage timeline" })).toBeInTheDocument()
  })
})
