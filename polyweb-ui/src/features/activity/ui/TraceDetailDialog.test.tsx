import { describe, expect, it, afterEach, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router"
import { ProjectScopeContext } from "@/domains/projects/state/context"
import { projectScopeValue } from "@/test/accessFixtures"
import { mapTraceDetail } from "@/domains/activity"
import type { TraceDetail } from "@/domains/activity"
import { TraceDetailDialog } from "./TraceDetailDialog"
import { ActivityPage } from "./ActivityPage"
import { installFetchStub, err, ok } from "@/test/fetchMock"
import {
  AGGREGATED_TRACE_ID,
  aggregatedTraceDetailFixture,
  errorTraceDetailFixture,
  traceDetailFixture,
  traceListFixture,
} from "@/test/fixtures/activity"

/**
 * Trace detail is the single disclosure point for sensitive content: a compact
 * context band, selected result details, timing, request data, and ranking
 * explanation. Outside this dialog the query and results never appear.
 */
function aggregatedDetail(): TraceDetail {
  return mapTraceDetail(aggregatedTraceDetailFixture())
}

function searchDetail(): TraceDetail {
  return mapTraceDetail(traceDetailFixture())
}

function renderDialog(detail: TraceDetail | null, overrides = {}) {
  const onClose = vi.fn()
  const onRetry = vi.fn()
  render(
    <TraceDetailDialog
      trace={detail}
      isOpen
      status="ready"
      error={null}
      onClose={onClose}
      onRetry={onRetry}
      {...overrides}
    />
  )
  return { onClose, onRetry }
}

describe("TraceDetailDialog", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("renders nothing when closed", () => {
    render(
      <TraceDetailDialog
        trace={searchDetail()}
        isOpen={false}
        status="ready"
        error={null}
        onClose={() => {}}
        onRetry={() => {}}
      />
    )

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  })

  it("shows the compact summary strip with status, provider, latency, and count", () => {
    renderDialog(aggregatedDetail())

    const dialog = screen.getByRole("dialog")
    expect(within(dialog).getAllByText("Provider").length).toBeGreaterThan(0)
    expect(within(dialog).getByText("All providers")).toBeInTheDocument()
    expect(within(dialog).getAllByText("Total latency").length).toBeGreaterThan(0)
    expect(within(dialog).getAllByText(/^3,?381 ?ms$/).length).toBeGreaterThan(0)
    expect(within(dialog).getByText("Success")).toBeInTheDocument()
    expect(within(dialog).getAllByText("6").length).toBeGreaterThan(0)
  })

  it("discloses the full query in the compact context band", () => {
    renderDialog(searchDetail())

    const label = screen.getByRole("heading", { name: "Query" })
    const query = screen.getByText("distributed consensus algorithms")
    const field = label.closest("section")
    expect(field).toHaveClass("items-center")
    expect(label.parentElement).toHaveClass("items-baseline")
    expect(label).toHaveClass("m-0", "leading-[18px]")
    expect(query).toHaveClass("m-0", "leading-[18px]")
  })

  it("labels the fetch input as its URL", () => {
    const detail = mapTraceDetail(errorTraceDetailFixture())
    renderDialog(detail)

    expect(screen.getByText("URL")).toBeInTheDocument()
    expect(
      screen.getByText("https://docs.polyweb.dev/getting-started")
    ).toBeInTheDocument()
  })

  it("lists fused results as compact selectable rows with rank, source, and fusion scores", async () => {
    const user = userEvent.setup()
    renderDialog(aggregatedDetail())

    const ranked = screen.getByRole("list", { name: "Ranked results" })
    expect(within(ranked).getAllByRole("button")).toHaveLength(6)
    // The title appears in the selected row and in its inspector.
    expect(
      screen.getAllByText("Reuters Latest Finance News | Today Top Headlines")
    ).toHaveLength(2)
    // The compact row keeps the recorded value on the common percentage scale.
    expect(within(ranked).getByText("70% match")).toBeInTheDocument()
    // One-line preview is readable in the row; the selected inspector keeps the full snippet.
    expect(
      within(ranked).getByText(
        "Exclusive news, data and analytics for financial market professionals."
      )
    ).toBeInTheDocument()
    expect(within(ranked).getAllByRole("button")[0]).toHaveAttribute("aria-pressed", "true")
    const inspector = screen.getByRole("region", { name: "Result inspector" })
    expect(
      within(inspector).getByText(
        "Exclusive news, data and analytics for financial market professionals."
      )
    ).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: /Reuters Latest Finance News/ }))
    expect(within(inspector).getByText("Fusion score")).toBeInTheDocument()
    expect(within(inspector).getByText("70% match")).toBeInTheDocument()
  })

  it("renders every recorded result with no show-all control", () => {
    const results = Array.from({ length: 5 }, (_, index) => ({
      title: `Result ${index + 1}`,
      url: `https://example.com/${index + 1}`,
      snippet: `Snippet ${index + 1}`,
      source: "keenable",
      score: 0.9,
    }))
    const detail = mapTraceDetail(
      traceDetailFixture({ output: { kind: "search_results", query: "q", results } })
    )
    renderDialog(detail)

    const ranked = screen.getByRole("list", { name: "Ranked results" })
    for (const index of [1, 2, 3, 4, 5]) {
      expect(within(ranked).getByText(`Result ${index}`)).toBeInTheDocument()
    }
    expect(screen.queryByRole("button", { name: /show all/i })).not.toBeInTheDocument()
  })

  it("shows plain excerpts and unpadded ranks in the list and inspector", () => {
    const detail = mapTraceDetail(traceDetailFixture({
      output: {
        kind: "search_results", query: "q",
        results: [{ title: "Example", url: "https://example.com", snippet: "- [*Guide*](https://example.com)", source: null, score: null }],
      },
    }))
    renderDialog(detail)
    const ranked = screen.getByRole("list", { name: "Ranked results" })
    expect(within(ranked).getByText("1")).toBeInTheDocument()
    expect(within(ranked).queryByText("01")).not.toBeInTheDocument()
    expect(within(ranked).getByText("Guide")).toBeInTheDocument()
    expect(within(screen.getByRole("region", { name: "Result inspector" })).getByText("Guide")).toBeInTheDocument()
  })

  it("opens on the first result and keeps the honest ranking explanation available", async () => {
    const user = userEvent.setup()
    renderDialog(aggregatedDetail())

    const inspector = screen.getByRole("region", { name: "Result inspector" })
    expect(within(inspector).getByText("Result 1 of 6")).toBeInTheDocument()
    expect(within(inspector).getByText("Reuters Latest Finance News | Today Top Headlines")).toBeInTheDocument()
    await user.click(within(inspector).getByText("Why this order"))
    expect(
      screen.getByText(/Results are shown in Polyweb's final fused order/)
    ).toBeInTheDocument()
    expect(screen.getByText(/Raw reciprocal-rank inputs/)).toBeInTheDocument()
    expect(
      screen.queryByRole("list", { name: "Output order and scores" })
    ).not.toBeInTheDocument()
    expect(screen.queryByText(/contributor not recorded/i)).not.toBeInTheDocument()
  })

  it("scopes results, score, and summary to the inspected provider attempt", async () => {
    const user = userEvent.setup()
    renderDialog(aggregatedDetail(), { providerSpanId: "a100000000000003" })

    // The provider identity renders as a logo badge followed by the name, so the
    // scope line holds separate elements instead of one text node. The badge
    // repeats in the scope line, the ranking sentence, and the result cards.
    const dialog = screen.getByRole("dialog")
    expect(within(dialog).getAllByText("Keenable").length).toBeGreaterThanOrEqual(2)
    expect(within(dialog).getAllByText(/response/).length).toBeGreaterThanOrEqual(2)
    expect(screen.queryByText("Results returned")).not.toBeInTheDocument()
    await user.click(screen.getByText("Why this order"))
    expect(
      screen.getByText(/Results keep the order returned by/)
    ).toBeInTheDocument()
    expect(screen.queryByText(/Fusion score/)).not.toBeInTheDocument()
    expect(screen.getByText("Provider latency")).toBeInTheDocument()
    expect(screen.getByText(/^2,?025 ?ms$/)).toBeInTheDocument()
    expect(
      screen.getByText(/Showing this provider's response/)
    ).toBeInTheDocument()
    // The row and selected inspector both retain the scoped provider score.
    const ranked = within(dialog).getByRole("list", { name: "Ranked results" })
    expect(within(ranked).getByText("92% match")).toBeInTheDocument()
    const inspector = within(dialog).getByRole("region", { name: "Result inspector" })
    expect(within(inspector).getByText("92% match")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: /Reuters Latest Finance News/ }))
    expect(within(inspector).getByText("Provider score")).toBeInTheDocument()
    expect(within(inspector).getByText("92% match")).toBeInTheDocument()
  })

  it("labels a single-provider trace with provider order, not fusion", async () => {
    const user = userEvent.setup()
    renderDialog(searchDetail())

    expect(
      screen.getByText(/Results keep the order returned by/)
    ).toBeInTheDocument()
    expect(screen.getAllByText("Keenable").length).toBeGreaterThanOrEqual(2)
    // The row and its default-selected inspector both retain the provider score.
    const ranked = screen.getByRole("list", { name: "Ranked results" })
    expect(within(ranked).getByText("94% match")).toBeInTheDocument()
    const inspector = screen.getByRole("region", { name: "Result inspector" })
    expect(within(inspector).getByText("94% match")).toBeInTheDocument()
    await user.click(screen.getByText("Why this order"))
    await user.click(screen.getByRole("button", { name: /Consensus algorithms explained/ }))
    expect(within(inspector).getByText("Provider score")).toBeInTheDocument()
    expect(within(inspector).getByText("94% match")).toBeInTheDocument()
    expect(screen.queryByText(/Fusion score/)).not.toBeInTheDocument()
    expect(screen.queryByText(/contributor not recorded/i)).not.toBeInTheDocument()
  })

  it("places inspector metadata before the snippet with no Source row", async () => {
    const user = userEvent.setup()
    renderDialog(aggregatedDetail())

    await user.click(screen.getByRole("button", { name: /Reuters Latest Finance News/ }))
    const inspector = screen.getByRole("region", { name: "Result inspector" })
    const html = inspector.innerHTML
    expect(html.indexOf("Fusion score")).toBeGreaterThan(-1)
    expect(html.indexOf("Fusion score")).toBeLessThan(html.indexOf("Target URL"))
    expect(html.indexOf("Target URL")).toBeLessThan(html.indexOf("Snippet summary"))
    expect(within(inspector).queryByText(/Source/)).not.toBeInTheDocument()
    expect(within(inspector).queryByText(/Source not recorded/)).not.toBeInTheDocument()
  })

  it("states the no-score fallback without inventing ranking arithmetic", async () => {
    const user = userEvent.setup()
    const detail = mapTraceDetail(
      traceDetailFixture({
        output: {
          kind: "search_results",
          query: "q",
          results: [
            { title: "A", url: "https://example.com/a", snippet: "", source: null, score: null },
            { title: "B", url: "https://example.com/b", snippet: "", source: null, score: null },
          ],
        },
      })
    )
    renderDialog(detail)

    const inspector = screen.getByRole("region", { name: "Result inspector" })
    expect(within(inspector).queryByText("Provider score")).not.toBeInTheDocument()
    await user.click(within(inspector).getByText("Why this order"))
    expect(
      screen.getByText(/This trace did not record provider scores, so returned order is the only ranking signal/)
    ).toBeInTheDocument()
    expect(screen.queryByText(/Only the final score is shown/)).not.toBeInTheDocument()
  })

  it("shows provider timing in the unified Timeline view instead of a separate latency panel", async () => {
    const user = userEvent.setup()
    renderDialog(aggregatedDetail())

    expect(screen.queryByText("Latency")).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Timeline" }))
    const trajectory = screen.getByRole("list", { name: "Trace trajectory" })
    const row = within(trajectory).getByRole("button", { name: /Keenable request/i })
    expect(within(row).getByText("Keenable")).toBeInTheDocument()
    expect(within(row).getByText("request")).toBeInTheDocument()
    expect(within(trajectory).getByText(/^2,?025 ?ms$/)).toBeInTheDocument()
  })

  it("keeps the approved narrow branches: 2×2 summary rail", () => {
    renderDialog(aggregatedDetail())

    const rail = screen.getByText("All providers").closest("dl")
    expect(rail?.className.split(" ")).toEqual(
      expect.arrayContaining(["grid-cols-2", "sm:grid-cols-4"])
    )
  })

  it("opens Timeline with the first payload-bearing span selected", async () => {
    const user = userEvent.setup()
    renderDialog(aggregatedDetail())

    await user.click(screen.getByRole("button", { name: "Timeline" }))
    expect(screen.getByRole("button", { name: /Keenable request/ })).toHaveAttribute(
      "aria-pressed",
      "true"
    )
    // Plain event labels with a relative time; the raw name stays in Technical identifiers.
    expect(screen.getAllByText("Provider request").length).toBeGreaterThan(0)
    expect(screen.queryByText(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/)).not.toBeInTheDocument()
  })

  it("shows an error callout with role=alert and no results for failed traces", () => {
    renderDialog(mapTraceDetail(errorTraceDetailFixture()))

    const alert = screen.getByRole("alert")
    expect(alert).toHaveTextContent("HTTP 502")
    // The raw error type stays out of the callout.
    expect(alert).not.toHaveTextContent("http_error")
    expect(screen.getByText("URL")).toBeInTheDocument()
    // Said once: the trace opens on its timeline with the one absence line.
    expect(screen.getAllByText(/no results were recorded/i)).toHaveLength(1)
    expect(
      within(screen.getByRole("group", { name: "Trace detail views" })).getByRole("button", {
        name: "Summary",
      })
    ).toHaveAttribute("aria-pressed", "true")
  })

  it("opens metadata-only traces on a compact summary with a Timeline action", async () => {
    const user = userEvent.setup()
    renderDialog({ ...searchDetail(), input: null, output: null })

    expect(screen.getByText("Metadata only")).toBeInTheDocument()
    expect(screen.getByText("Query not stored")).toBeInTheDocument()
    expect(screen.queryByText(/stored metadata only/)).not.toBeInTheDocument()
    expect(screen.getAllByText("Results were not stored (metadata-only trace policy)")).toHaveLength(1)
    expect(screen.getByRole("button", { name: "Summary" })).toHaveAttribute("aria-pressed", "true")
    expect(screen.queryByRole("list", { name: "Trace trajectory" })).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Timeline" }))
    expect(screen.getByRole("list", { name: "Trace trajectory" })).toBeInTheDocument()
    expect(screen.queryByText("Results were not stored (metadata-only trace policy)")).not.toBeInTheDocument()
  })

  it("names what ran and when in the subtitle, with no storage copy", () => {
    renderDialog(searchDetail())

    const dialog = screen.getByRole("dialog")
    expect(within(dialog).getByText(/^Search · /)).toBeInTheDocument()
    expect(within(dialog).queryByText(/Stored in this Polyweb database/)).not.toBeInTheDocument()
  })

  it("says the results were not stored for a success without output", () => {
    renderDialog({ ...searchDetail(), output: null })

    expect(screen.getByText("The results of this trace were not stored")).toBeInTheDocument()
    expect(screen.queryByText(/stored metadata only/)).not.toBeInTheDocument()
  })

  it("shows no payload notice when the query and results were captured", () => {
    renderDialog(searchDetail())

    expect(screen.queryByText(/stored metadata only/)).not.toBeInTheDocument()
    expect(screen.queryByText(/were not stored/)).not.toBeInTheDocument()
  })

  it("shows the project copy without retry for a trace outside the project", () => {
    renderDialog(null, { status: "missing", error: "This trace is not available in this project." })

    expect(screen.getByRole("alert")).toHaveTextContent("This trace is not available in this project")
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument()
  })

  it("shows a loading state while detail is in flight", () => {
    renderDialog(null, { status: "loading" })

    expect(screen.getByRole("status")).toHaveTextContent(/loading trace detail/i)
  })

  it("shows an error state with retry when detail fails", async () => {
    const user = userEvent.setup()
    const { onRetry } = renderDialog(null, {
      status: "error",
      error: "boom",
    })

    expect(screen.getByRole("alert")).toHaveTextContent(/trace detail unavailable/i)
    await user.click(screen.getByRole("button", { name: "Retry" }))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it("closes on Escape and returns focus to the invoking control", async () => {
    installFetchStub((req) => {
      if (req.method === "GET" && /^\/api\/v1\/projects\/[^/]+\/traces\//.test(req.url)) {
        const traceId = decodeURIComponent(req.url.split("/").pop() ?? "")
        if (traceId === AGGREGATED_TRACE_ID) return ok(aggregatedTraceDetailFixture())
        return ok(traceDetailFixture())
      }
      if (req.method === "GET" && /^\/api\/v1\/projects\/[^/]+\/traces/.test(req.url)) {
        return ok(traceListFixture())
      }
      return err(404, { detail: "unhandled test route" })
    })
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <ProjectScopeContext.Provider value={projectScopeValue()}>
          <ActivityPage />
        </ProjectScopeContext.Provider>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: "View details" })).toHaveLength(3)
    })
    const trigger = screen.getAllByRole("button", { name: "View details" })[0]!
    await user.click(trigger)
    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeInTheDocument()
    })
    expect(screen.getByText("What is the latest financial news?")).toBeInTheDocument()

    await user.keyboard("{Escape}")
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    })
    expect(trigger).toHaveFocus()
  })
})

/**
 * The rebuilt dialog (PLAN §6.3 item 5): 7xl modal, one aligned `<dl>` summary
 * compact context band, two inspection views, and a default-selected result.
 */
describe("TraceDetailDialog inspector workspace", () => {
  function renderAggregated(overrides = {}) {
    const onClose = vi.fn()
    const onRetry = vi.fn()
    render(
      <TraceDetailDialog
        trace={mapTraceDetail(aggregatedTraceDetailFixture())}
        isOpen
        status="ready"
        error={null}
        onClose={onClose}
        onRetry={onRetry}
        {...overrides}
      />
    )
    return { onClose, onRetry }
  }

  it("uses the wider 7xl modal with one aligned dl summary rail", () => {
    renderAggregated()

    expect(document.querySelector(".sm\\:max-w-7xl")).not.toBeNull()
    const rail = document.querySelector("dl")
    expect(rail).not.toBeNull()
    expect(rail?.querySelectorAll(":scope > div")).toHaveLength(4)
  })

  it("keeps the concise fusion explanation available without a duplicate list", async () => {
    const user = userEvent.setup()
    renderAggregated()

    await user.click(screen.getByText("Why this order"))
    expect(
      screen.getByText(/Results are shown in Polyweb.s final fused order/)
    ).toBeInTheDocument()
    expect(screen.getByText(/Raw reciprocal-rank inputs/)).toBeInTheDocument()
    expect(
      screen.queryByRole("list", { name: "Output order and scores" })
    ).not.toBeInTheDocument()
    expect(screen.queryByText(/contributor not recorded/i)).not.toBeInTheDocument()
  })

  it("switches between Results and one complete Timeline view", async () => {
    const user = userEvent.setup()
    renderAggregated()

    const switcher = screen.getByRole("group", { name: "Trace detail views" })
    expect(within(switcher).getByRole("button", { name: "Results" })).toHaveAttribute(
      "aria-pressed",
      "true"
    )
    await user.click(within(switcher).getByRole("button", { name: "Timeline" }))
    expect(within(switcher).getByRole("button", { name: "Timeline" })).toHaveAttribute(
      "aria-pressed",
      "true"
    )
    expect(screen.getByRole("region", { name: "Trace timeline" })).toBeInTheDocument()
    expect(within(switcher).queryByRole("button", { name: "Request data" })).not.toBeInTheDocument()
    const details = screen.getByRole("region", { name: /details/i })
    expect(within(details).getByRole("button", { name: "Show raw data" })).toBeInTheDocument()
    expect(
      screen.getByText("Select a stage to see its timing and recorded data")
    ).toBeInTheDocument()
  })

  it("keeps the timeline beside selected span details and labels the whole-trace scope", async () => {
    const user = userEvent.setup()
    renderAggregated()

    await user.click(screen.getByRole("button", { name: "Timeline" }))

    const timeline = screen.getByRole("region", { name: "Trace timeline" })
    expect(timeline.parentElement?.className).toMatch(/lg:grid-cols-/)
    expect(screen.getByRole("region", { name: /details/i })).toBeInTheDocument()
    expect(
      screen.getByText("Select a stage to see its timing and recorded data")
    ).toBeInTheDocument()
  })

  it("selects the first result and shows its full snippet beside the compact list", () => {
    renderAggregated()

    const ranked = screen.getByRole("list", { name: "Ranked results" })
    expect(
      within(ranked).getByText("Exclusive news, data and analytics for financial market professionals.")
    ).toBeInTheDocument()
    expect(within(ranked).getAllByRole("button")[0]).toHaveAttribute("aria-pressed", "true")
    expect(
      within(screen.getByRole("region", { name: "Result inspector" })).getByText(
        "Exclusive news, data and analytics for financial market professionals."
      )
    ).toBeInTheDocument()
  })

  it("has no old duplicate panels: no separate Latency section or technical disclosure", () => {
    renderAggregated()

    expect(screen.queryByText("Latency")).not.toBeInTheDocument()
    expect(screen.queryByText("Technical trajectory")).not.toBeInTheDocument()
    expect(screen.queryByText("Results returned")).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /show all/i })).not.toBeInTheDocument()
  })

})
