import { describe, expect, it, afterEach, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { mapTraceDetail } from "@/domains/activity"
import type { TraceDetail } from "@/domains/activity"
import { TraceDetailDialog } from "./TraceDetailDialog"
import { ActivityPage } from "./ActivityPage"
import { installFetchStub, err, ok } from "@/test/fetchMock"
import {
  errorTraceDetailFixture,
  traceDetailFixture,
  traceListFixture,
} from "@/test/fixtures/activity"

/**
 * Trace detail is the single disclosure point for sensitive content: the
 * summary strip first, then the full query, the returned results, the stage
 * timeline, and finally the collapsed technical projection. Outside this
 * dialog the query and results never appear.
 */
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

  it("shows the summary strip with status, provider, latency, and count", () => {
    renderDialog(searchDetail())

    expect(screen.getByText("Status")).toBeInTheDocument()
    expect(screen.getByText("success")).toBeInTheDocument()
    expect(screen.getByText("Provider")).toBeInTheDocument()
    expect(screen.getByText("Keenable")).toBeInTheDocument()
    const latencyCell = screen.getByText("Total latency").closest("div")!
    expect(within(latencyCell).getByText("248ms")).toBeInTheDocument()
    const resultsCell = screen.getByText("Results").closest("div")!
    expect(within(resultsCell).getByText("2")).toBeInTheDocument()
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

  it("lists returned results with title, URL, and snippet", () => {
    renderDialog(searchDetail())

    expect(screen.getByText("Results returned")).toBeInTheDocument()
    expect(screen.getByText("Consensus algorithms explained")).toBeInTheDocument()
    expect(
      screen.getByText("https://docs.freesearch.dev/consensus")
    ).toBeInTheDocument()
    expect(screen.getByText("Raft, Paxos, and where each applies.")).toBeInTheDocument()
    expect(screen.getByText("Raft vs Paxos")).toBeInTheDocument()
  })

  it("bounds long result lists behind a show-all control", async () => {
    const user = userEvent.setup()
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

    expect(screen.getByText("Result 3")).toBeInTheDocument()
    expect(screen.queryByText("Result 4")).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Show all 5" }))
    expect(screen.getByText("Result 4")).toBeInTheDocument()
    expect(screen.getByText("Result 5")).toBeInTheDocument()
  })

  it("shows an error callout with role=alert and no results for failed traces", () => {
    renderDialog(mapTraceDetail(errorTraceDetailFixture()))

    const alert = screen.getByRole("alert")
    expect(alert).toHaveTextContent("http_error")
    expect(alert).toHaveTextContent("HTTP 502")
    expect(screen.getByText("URL fetched")).toBeInTheDocument()
    expect(screen.getByText(/no results were recorded/i)).toBeInTheDocument()
  })

  it("keeps Technical details collapsed while the timeline is disclosed", () => {
    renderDialog(searchDetail())

    const timeline = screen.getByText("Stage timeline").closest("details")!
    expect(timeline.hasAttribute("open")).toBe(true)
    const technical = screen.getByText("Technical details").closest("details")!
    expect(technical.hasAttribute("open")).toBe(false)
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
      expect(screen.getAllByRole("button", { name: "View details" })).toHaveLength(2)
    })
    const trigger = screen.getAllByRole("button", { name: "View details" })[0]!
    await user.click(trigger)
    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeInTheDocument()
    })
    expect(screen.getByText("distributed consensus algorithms")).toBeInTheDocument()

    await user.keyboard("{Escape}")
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    })
    expect(trigger).toHaveFocus()
  })
})
