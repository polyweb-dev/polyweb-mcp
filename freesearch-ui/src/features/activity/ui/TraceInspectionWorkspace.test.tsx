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
 * The Results/Trace workspace. It owns the
 * ephemeral view/result/span selection inside one shared split shell:
 * - keyed by traceId + providerSpanId (selection resets across traces);
 * - result identity is the scoped index, so duplicate URLs stay distinct;
 * - selecting another result/trajectory row replaces the side payload;
 * - one trace inspector surfaces span timing, payloads, and trace-level details;
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
  it("starts with the first result selected and opens one complete trace view", async () => {
    const user = userEvent.setup()
    renderWorkspace(aggregated())

    const switcher = screen.getByRole("group", { name: "Trace detail views" })
    expect(within(switcher).getByRole("button", { name: "Results" })).toHaveAttribute(
      "aria-pressed",
      "true"
    )
    expect(within(screen.getByRole("list", { name: "Ranked results" })).getAllByRole("button")[0])
      .toHaveAttribute("aria-pressed", "true")

    await user.click(within(switcher).getByRole("button", { name: "Trace" }))
    expect(within(switcher).getByRole("button", { name: "Trace" })).toHaveAttribute(
      "aria-pressed",
      "true"
    )
    expect(screen.getByRole("region", { name: "Trace timeline" })).toBeInTheDocument()
    expect(screen.getByRole("list", { name: "Trace trajectory" })).toBeInTheDocument()
    expect(within(switcher).queryByRole("button", { name: "Request data" })).not.toBeInTheDocument()

    const inspector = screen.getByRole("region", { name: /details/i })
    expect(within(inspector).getByText("freesearch.provider.request")).toBeInTheDocument()
    expect(within(inspector).getByLabelText("freesearch.provider.request attributes")).toHaveTextContent(
      "What is the latest financial news?"
    )
    const responseAttributes = within(inspector).getByLabelText(
      "freesearch.provider.response attributes"
    )
    expect(responseAttributes).toHaveTextContent('"result_count": 3')
    await user.click(within(responseAttributes).getByText("3 items"))
    await user.click(within(responseAttributes).getAllByText("5 keys")[0]!)
    expect(responseAttributes).toHaveTextContent("Reuters Latest Finance News")
    await user.click(within(inspector).getByText("Recorded output"))
    expect(within(inspector).getByRole("group", { name: "Recorded output JSON" })).toBeInTheDocument()
  })

  it("keeps the waterfall provider rows consistent and preserves their recorded payload", async () => {
    const user = userEvent.setup()
    const { container } = renderWorkspace(aggregated())

    await user.click(screen.getByRole("button", { name: "Trace" }))

    const timeline = screen.getByRole("region", { name: "Trace timeline" })
    const detail = screen.getByRole("region", { name: /details/i })
    const split = timeline.parentElement as HTMLElement
    expect(container.contains(split)).toBe(true)
    expect(split.className).toMatch(/lg:grid-cols-/)
    expect(detail).toBeInTheDocument()
    expect(within(detail).getByText("freesearch.provider.request")).toBeInTheDocument()

    const providerRow = within(screen.getByRole("list", { name: "Trace trajectory" })).getByRole(
      "button",
      { name: /Keenable request/ }
    )
    const trajectory = screen.getByRole("list", { name: "Trace trajectory" })
    expect(within(trajectory).getAllByRole("button")).toHaveLength(11)
    expect(within(trajectory).queryByRole("button", { name: /HTTP request|Response parsing/ })).not.toBeInTheDocument()
    expect(within(trajectory).queryByText(/Provider steps|Other recorded steps|Recorded substeps/)).not.toBeInTheDocument()

    await user.click(providerRow)
    expect(within(detail).getByLabelText("freesearch.provider.response attributes")).toHaveTextContent(
      '"result_count": 3'
    )
    await user.click(within(detail).getByText("Technical identifiers"))
    expect(within(detail).getByText("Span").parentElement).toHaveTextContent("a100000000000003")
    expect(within(detail).getByText("freesearch.provider")).toBeInTheDocument()
  })

  it("gives the timeline and span payload their own readable scroll regions", async () => {
    const user = userEvent.setup()
    renderWorkspace(aggregated())

    await user.click(screen.getByRole("button", { name: "Trace" }))

    const timeline = screen.getByRole("region", { name: "Trace timeline" })
    const details = screen.getByRole("region", { name: /details/i })
    expect(timeline.firstElementChild?.className).toMatch(/min-h-0/)
    expect(details.firstElementChild?.className).toMatch(/overflow-y-auto/)
    expect(screen.queryByText("Select a trajectory row to inspect its timing and payload.")).not.toBeInTheDocument()
    expect(screen.getByRole("list", { name: "Trace trajectory" })).toBeInTheDocument()
  })

  it("keeps trace details available when no span timing was recorded", async () => {
    const user = userEvent.setup()
    const detail = aggregated()
    detail.stages = []
    const { container } = renderWorkspace(detail)

    const workspace = container.firstElementChild as HTMLElement
    expect(workspace.className).toMatch(/h-full/)
    expect(workspace.className).toMatch(/flex-1/)

    await user.click(screen.getByRole("button", { name: "Trace" }))

    expect(screen.getByRole("region", { name: "Trace timeline" })).toBeInTheDocument()
    const inspector = screen.getByRole("region", { name: /details/i })
    expect(within(inspector).getByText("No span timing was recorded for this trace.")).toBeInTheDocument()
    await user.click(within(inspector).getByText("Trace metadata"))
    expect(within(inspector).getByText("Trace ID").parentElement).toHaveTextContent(detail.traceId)
    await user.click(within(inspector).getByText("Recorded output"))
    expect(within(inspector).getByRole("group", { name: "Recorded output JSON" })).toBeInTheDocument()
  })

  it("resets selection when the trace identity changes", async () => {
    const user = userEvent.setup()
    const first = aggregated()
    const { rerender } = renderWorkspace(first)

    await user.click(screen.getAllByRole("button", { name: /Reuters|Yahoo|CNBC|Financial|Bloomberg|MarketWatch/ })[0]!)
    const inspector = screen.getByRole("region", { name: "Result inspector" })
    expect(
      within(inspector).getByText("Exclusive news, data and analytics for financial market professionals.")
    ).toBeInTheDocument()

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
    const dupInspector = screen.getByRole("region", { name: "Result inspector" })
    expect(within(dupInspector).getByText("Snippet two")).toBeInTheDocument()
    expect(within(dupInspector).queryByText("Snippet one")).not.toBeInTheDocument()
  })

  it("replaces the side payload instead of appending it", async () => {
    const user = userEvent.setup()
    renderWorkspace(aggregated())

    const rows = screen.getAllByRole("button", { name: /Reuters|Yahoo|CNBC|Financial|Bloomberg|MarketWatch/ })
    await user.click(rows[0]!)
    const replaceInspector = screen.getByRole("region", { name: "Result inspector" })
    expect(
      within(replaceInspector).getByText("Exclusive news, data and analytics for financial market professionals.")
    ).toBeInTheDocument()
    await user.click(rows[1]!)
    expect(within(replaceInspector).getByText("Market coverage six days ago.")).toBeInTheDocument()
    expect(
      within(replaceInspector).queryByText("Exclusive news, data and analytics for financial market professionals.")
    ).not.toBeInTheDocument()
  })

  it("selects the first payload-bearing trace row and shows its provider payload", async () => {
    const user = userEvent.setup()
    renderWorkspace(aggregated())

    await user.click(screen.getByRole("button", { name: "Trace" }))
    const providerRow = screen.getByRole("button", { name: /Keenable request/ })
    expect(providerRow).toHaveAttribute("aria-pressed", "true")
    const payloadRegion = screen.getByRole("region", { name: /details/i })
    expect(within(payloadRegion).getByText("Keenable")).toBeInTheDocument()
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

    expect(screen.getByText("Keenable")).toBeInTheDocument()
    expect(screen.getByText(/response/)).toBeInTheDocument()
    expect(screen.queryByText(/fusion/i)).not.toBeInTheDocument()
  })

  it("shows the complete recorded fetch document in its full-height pane", () => {
    const content = "Stored document body. ".repeat(40)
    const detail = mapTraceDetail(errorTraceDetailFixture({
      output: {
        kind: "fetch_document",
        url: "https://example.com/doc",
        title: "Doc",
        content,
        content_length: content.length,
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

    const article = screen.getByRole("article")
    expect(article.querySelector("pre")?.textContent).toBe(content)
    expect(within(article).queryByRole("button", { name: /show full content/i })).not.toBeInTheDocument()
    expect(vi.fn()).not.toHaveBeenCalled()
  })
})
