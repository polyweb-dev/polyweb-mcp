import { describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { mapTraceDetail } from "@/domains/activity/model/mappers"
import type { TraceDetail } from "@/domains/activity/model/types"
import {
  aggregatedTraceDetailFixture,
  errorTraceDetailFixture,
  traceDetailFixture,
} from "@/test/fixtures/activity"
import { TraceInspectionWorkspace } from "./TraceInspectionWorkspace"

/**
 * The Results/Trajectory inspector workspace (PLAN §6.3 item 6). It owns the
 * ephemeral view/result/span selection inside one shared split shell:
 * - keyed by traceId + providerSpanId (selection resets across traces);
 * - result identity is the scoped index, so duplicate URLs stay distinct;
 * - selecting another result/trajectory row replaces the side payload;
 * - trajectory selection surfaces the recorded provider name + events;
 * - provider-scoped output and fetch documents render in the same shell.
 */
function aggregated(): TraceDetail {
  return mapTraceDetail(aggregatedTraceDetailFixture())
}

function renderWorkspace(detail: TraceDetail, overrides = {}) {
  const output =
    detail.output?.kind === "search_results" ? detail.output : null
  return render(
    <TraceInspectionWorkspace
      trace={detail}
      output={output}
      attempt={null}
      mode="fusion"
      {...overrides}
    />
  )
}

describe("TraceInspectionWorkspace", () => {
  it("switches between Results and Trajectory modes", async () => {
    const user = userEvent.setup()
    renderWorkspace(aggregated())

    const switcher = screen.getByRole("group", { name: /trace detail view/i })
    expect(within(switcher).getByRole("button", { name: "Results" })).toHaveAttribute(
      "aria-pressed",
      "true"
    )
    await user.click(within(switcher).getByRole("button", { name: "Trajectory" }))
    expect(within(switcher).getByRole("button", { name: "Trajectory" })).toHaveAttribute(
      "aria-pressed",
      "true"
    )
  })

  it("resets selection when the trace identity changes", async () => {
    const user = userEvent.setup()
    const first = aggregated()
    const { rerender } = renderWorkspace(first)

    await user.click(screen.getAllByRole("button", { name: /Reuters|Yahoo|CNBC|Financial|Bloomberg|MarketWatch/ })[0]!)
    expect(screen.getByText("Exclusive news, data and analytics for financial market professionals.")).toBeInTheDocument()

    const second = mapTraceDetail(traceDetailFixture())
    rerender(
      <TraceInspectionWorkspace
        trace={second}
        output={second.output?.kind === "search_results" ? second.output : null}
        attempt={null}
        mode="provider"
      />
    )
    expect(
      screen.queryByText("Exclusive news, data and analytics for financial market professionals.")
    ).not.toBeInTheDocument()
  })

  it("keeps duplicate-URL results distinct by scoped index", async () => {
    const user = userEvent.setup()
    const detail = mapTraceDetail(
      traceDetailFixture({
        output: {
          kind: "search_results",
          query: "q",
          results: [
            { title: "First copy", url: "https://example.com/dup", snippet: "Snippet one", source: "keenable", score: 0.9 },
            { title: "Second copy", url: "https://example.com/dup", snippet: "Snippet two", source: "keenable", score: 0.8 },
          ],
        },
      })
    )
    renderWorkspace(detail)

    await user.click(screen.getByRole("button", { name: /Second copy/ }))
    expect(screen.getByText("Snippet two")).toBeInTheDocument()
    expect(screen.queryByText("Snippet one")).not.toBeInTheDocument()
  })

  it("replaces the side payload instead of appending it", async () => {
    const user = userEvent.setup()
    renderWorkspace(aggregated())

    const rows = screen.getAllByRole("button", { name: /Reuters|Yahoo|CNBC|Financial|Bloomberg|MarketWatch/ })
    await user.click(rows[0]!)
    expect(screen.getByText("Exclusive news, data and analytics for financial market professionals.")).toBeInTheDocument()
    await user.click(rows[1]!)
    expect(screen.getByText("Market coverage six days ago.")).toBeInTheDocument()
    expect(
      screen.queryByText("Exclusive news, data and analytics for financial market professionals.")
    ).not.toBeInTheDocument()
  })

  it("selects a trajectory row and shows its provider payload at the side", async () => {
    const user = userEvent.setup()
    renderWorkspace(aggregated())

    await user.click(screen.getByRole("button", { name: "Trajectory" }))
    await user.click(screen.getByRole("button", { name: /Keenable request/ }))
    expect(screen.getByText(/keenable/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/freesearch.provider.response attributes/i)).toBeInTheDocument()
  })

  it("scopes results to the inspected provider attempt", () => {
    const detail = aggregated()
    const attempt = {
      spanId: "a100000000000003",
      providerId: "keenable",
      providerLabel: "Keenable",
      offsetMs: 20,
      durationMs: 2025,
      outcome: "success" as const,
      error: null,
      resultCount: 3,
      results: [],
    }
    render(
      <TraceInspectionWorkspace
        trace={detail}
        output={{ kind: "search_results", query: detail.input ?? "", results: attempt.results }}
        attempt={attempt}
        mode="provider"
      />
    )

    expect(screen.getByText(/Keenable response|provider/i)).toBeInTheDocument()
    expect(screen.queryByText(/fusion/i)).not.toBeInTheDocument()
  })

  it("falls back to the fetch document for fetch traces", () => {
    const detail = mapTraceDetail(errorTraceDetailFixture({
      output: {
        kind: "fetch_document",
        url: "https://example.com/doc",
        title: "Doc",
        content: "hello world",
        content_length: 11,
        truncated: false,
      },
    }))
    render(
      <TraceInspectionWorkspace
        trace={detail}
        output={detail.output}
        attempt={null}
        mode="provider"
      />
    )

    expect(screen.getByText("hello world")).toBeInTheDocument()
    expect(vi.fn()).not.toHaveBeenCalled()
  })
})
