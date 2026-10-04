import { describe, expect, it, afterEach, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
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
 * telemetry strip, the query, bounded results, the honest ranking explanation,
 * the simplified provider-vs-FreeSearch latency, and the collapsed technical
 * trajectory. Outside this dialog the query and results never appear.
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
    expect(within(dialog).getAllByText("3381ms").length).toBeGreaterThan(0)
    expect(within(dialog).getByText("Success")).toBeInTheDocument()
    expect(within(dialog).getAllByText("6").length).toBeGreaterThan(0)
  })

  it("discloses the full query under Query sent", () => {
    renderDialog(searchDetail())

    expect(screen.getByText("Query sent")).toBeInTheDocument()
    expect(screen.getByText("distributed consensus algorithms")).toBeInTheDocument()
  })

  it("labels the fetch input as the URL fetched", () => {
    const detail = mapTraceDetail(errorTraceDetailFixture())
    renderDialog(detail)

    expect(screen.getByText("URL fetched")).toBeInTheDocument()
    expect(
      screen.getByText("https://docs.freesearch.dev/getting-started")
    ).toBeInTheDocument()
  })

  it("lists fused results as compact selectable rows with rank, source, and fusion scores", async () => {
    const user = userEvent.setup()
    renderDialog(aggregatedDetail())

    const ranked = screen.getByRole("list", { name: "Ranked results" })
    expect(within(ranked).getAllByRole("button")).toHaveLength(6)
    // Titles appear once, in the list only: the ranking explanation no longer repeats them.
    expect(
      screen.getAllByText("Reuters Latest Finance News | Today Top Headlines")
    ).toHaveLength(1)
    // The shared card shows the recorded value on the common percentage scale.
    expect(within(ranked).getByText("70% match")).toBeInTheDocument()
    // R8: the shared card carries a two-line snippet, so the text is present in the row.
    expect(
      within(ranked).getByText(
        "Exclusive news, data and analytics for financial market professionals."
      )
    ).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: /Reuters Latest Finance News/ }))
    const inspector = screen.getByRole("region", { name: "Result inspector" })
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

  it("explains fusion order once in the side inspector with the honest RRF note", () => {
    renderDialog(aggregatedDetail())

    expect(
      screen.getByText(
        "Select a result to inspect its full snippet, URL, and recorded score."
      )
    ).toBeInTheDocument()
    expect(screen.getByText("Why this order")).toBeInTheDocument()
    expect(
      screen.getByText(/Results are shown in FreeSearch's final fused order/)
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
    expect(
      screen.getByText(/Results keep the order returned by/)
    ).toBeInTheDocument()
    expect(screen.queryByText(/Fusion score/)).not.toBeInTheDocument()
    expect(screen.getByText("Provider latency")).toBeInTheDocument()
    expect(screen.getByText("2025ms")).toBeInTheDocument()
    expect(
      screen.getByText(/Showing this provider's response/)
    ).toBeInTheDocument()
    // The shared card shows the value on the common percentage scale.
    expect(within(dialog).getByText("92% match")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: /Reuters Latest Finance News/ }))
    const inspector = screen.getByRole("region", { name: "Result inspector" })
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
    // The shared card shows the value on the common percentage scale.
    expect(screen.getByText("94% match")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: /Consensus algorithms explained/ }))
    const inspector = screen.getByRole("region", { name: "Result inspector" })
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

  it("states the no-score fallback without inventing ranking arithmetic", () => {
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

    expect(
      screen.getByText(/This trace did not record provider scores, so returned order is the only ranking signal/)
    ).toBeInTheDocument()
    expect(screen.queryByText(/Only the final score is shown/)).not.toBeInTheDocument()
  })

  it("fuses provider timing into trajectory rows instead of a separate latency panel", async () => {
    const user = userEvent.setup()
    renderDialog(aggregatedDetail())

    expect(screen.queryByText("Latency")).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Trajectory" }))
    const trajectory = screen.getByRole("list", { name: "Trace trajectory" })
    const row = within(trajectory).getByRole("button", { name: /Keenable request/i })
    expect(within(row).getByText("Keenable")).toBeInTheDocument()
    expect(within(row).getByText("request")).toBeInTheDocument()
    expect(within(trajectory).getByText("2025ms")).toBeInTheDocument()
  })

  it("keeps the approved narrow branches: 2×2 summary rail", () => {
    renderDialog(aggregatedDetail())

    const rail = screen.getByText("All providers").closest("dl")
    expect(rail?.className.split(" ")).toEqual(
      expect.arrayContaining(["grid-cols-2", "sm:grid-cols-4"])
    )
  })

  it("selects a trajectory row and shows its payload in the side inspector", async () => {
    const user = userEvent.setup()
    renderDialog(aggregatedDetail())

    await user.click(screen.getByRole("button", { name: "Trajectory" }))
    expect(
      screen.getByText("Select a trajectory row to inspect its timing and payload.")
    ).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: /Keenable request/ }))
    expect(
      screen.queryByText("Select a trajectory row to inspect its timing and payload.")
    ).not.toBeInTheDocument()
    expect(screen.getByText("freesearch.provider.request")).toBeInTheDocument()
  })

  it("shows an error callout with role=alert and no results for failed traces", () => {
    renderDialog(mapTraceDetail(errorTraceDetailFixture()))

    const alert = screen.getByRole("alert")
    expect(alert).toHaveTextContent("http_error")
    expect(alert).toHaveTextContent("HTTP 502")
    expect(screen.getByText("URL fetched")).toBeInTheDocument()
    expect(screen.getByText(/no results were recorded/i)).toBeInTheDocument()
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
      if (req.method === "GET" && req.url.startsWith("/api/v1/traces/")) {
        const traceId = decodeURIComponent(req.url.split("/").pop() ?? "")
        if (traceId === AGGREGATED_TRACE_ID) return ok(aggregatedTraceDetailFixture())
        return ok(traceDetailFixture())
      }
      if (req.method === "GET" && req.url.startsWith("/api/v1/traces")) {
        return ok(traceListFixture())
      }
      return err(404, { detail: "unhandled test route" })
    })
    const user = userEvent.setup()
    render(<ActivityPage />)

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
 * rail, concise mode-specific order copy, a Results/Trajectory switch, and a
 * selected side payload.
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

  it("states fusion order once with the concise copy and no duplicate list", () => {
    renderAggregated()

    expect(
      screen.getByText(/Results are shown in FreeSearch.s final fused order/)
    ).toBeInTheDocument()
    expect(screen.getByText(/Raw reciprocal-rank inputs/)).toBeInTheDocument()
    expect(
      screen.queryByRole("list", { name: "Output order and scores" })
    ).not.toBeInTheDocument()
    expect(screen.queryByText(/contributor not recorded/i)).not.toBeInTheDocument()
  })

  it("switches between Results and Trajectory modes", async () => {
    const user = userEvent.setup()
    renderAggregated()

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

  it("keeps rows compact and shows the full snippet in the side inspector", async () => {
    const user = userEvent.setup()
    renderAggregated()

    // R8: the shared card carries a two-line snippet in the row; selection fills the inspector.
    const ranked = screen.getByRole("list", { name: "Ranked results" })
    expect(
      within(ranked).getByText("Exclusive news, data and analytics for financial market professionals.")
    ).toBeInTheDocument()
    const inspector = screen.getByRole("region", { name: "Result inspector" })
    expect(
      within(inspector).queryByText("Exclusive news, data and analytics for financial market professionals.")
    ).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: /Reuters Latest Finance News/ }))
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

  it("preserves loading, error, and Escape behavior in the new shell", async () => {
    const { onRetry } = (() => {
      const onClose = vi.fn()
      const retry = vi.fn()
      render(
        <TraceDetailDialog
          trace={null}
          isOpen
          status="error"
          error="boom"
          onClose={onClose}
          onRetry={retry}
        />
      )
      return { onRetry: retry }
    })()

    expect(screen.getByRole("alert")).toHaveTextContent(/trace detail unavailable/i)
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Retry" }))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })
})
