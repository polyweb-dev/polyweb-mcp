import { describe, expect, it, afterEach, vi } from "vitest"
import { act, render, screen, waitFor, within } from "@testing-library/react"
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

  it("shows the compact summary strip with status, provider, attribution, latency, and count", () => {
    renderDialog(aggregatedDetail())

    const dialog = screen.getByRole("dialog")
    expect(within(dialog).getAllByText("Provider").length).toBeGreaterThan(0)
    expect(within(dialog).getByText("All providers")).toBeInTheDocument()
    expect(within(dialog).getAllByText("Initiated by").length).toBeGreaterThan(0)
    expect(within(dialog).getAllByText("Total latency").length).toBeGreaterThan(0)
    expect(within(dialog).getAllByText(/^3,?381 ?ms$/).length).toBeGreaterThan(0)
    expect(within(dialog).getByText("Success")).toBeInTheDocument()
    expect(within(dialog).getAllByText("6").length).toBeGreaterThan(0)
    expect(
      within(dialog).getByText("Initiated by").closest("div")
    ).toHaveTextContent("—")
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
    // Logo, provider name, and `request` are ONE text element in one centered
    // flex row, so they share a baseline instead of "Keenable" riding higher.
    const label = within(row).getByText("Keenable request")
    expect(label).toBeInTheDocument()
    expect(within(row).getByTestId("provider-logo-keenable").parentElement).toBe(label.parentElement)
    expect(label.parentElement).toHaveClass("inline-flex", "items-center")
    expect(row.querySelector('[title="Keenable request"]')).toHaveClass("flex", "items-center")
    expect(within(trajectory).getByText(/^2,?025 ?ms$/)).toBeInTheDocument()
  })

  it("keeps the approved responsive rail: 2×2 narrow, 3 from sm, 5 on wide", () => {
    renderDialog(aggregatedDetail())

    const rail = screen.getByText("All providers").closest("dl")
    expect(rail?.className.split(" ")).toEqual(
      expect.arrayContaining(["grid-cols-2", "sm:grid-cols-3", "lg:grid-cols-5"])
    )
    expect(rail?.className).not.toContain("sm:grid-cols-4")
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
 * TASK-000002 owner request: a trace that can be inspected can be copied.
 * Copy JSON writes the decoded detail as shown, exactly as stored, and says
 * Copied only after the write succeeds.
 */
describe("TraceDetailDialog Copy JSON", () => {
  const clipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, "clipboard")

  // After userEvent.setup(), which installs its own clipboard stub.
  function mockClipboard(writeText: (text: string) => Promise<void>): void {
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true })
  }

  afterEach(() => {
    if (clipboardDescriptor) {
      Object.defineProperty(navigator, "clipboard", clipboardDescriptor)
    } else {
      Reflect.deleteProperty(navigator, "clipboard")
    }
  })

  it("shows Copy JSON as an icon button with a Copy JSON tooltip", async () => {
    const user = userEvent.setup()
    renderDialog(searchDetail())

    const button = screen.getByRole("button", { name: "Copy JSON" })
    expect(button.textContent).toBe("")
    await user.hover(button)

    expect(await screen.findByText("Copy JSON")).toBeInTheDocument()
  })

  it("copies the shown trace as pretty-printed JSON and confirms with Copied", async () => {
    const user = userEvent.setup()
    const writeText = vi.fn(async (_text: string) => {})
    mockClipboard(writeText)
    const detail = searchDetail()
    renderDialog(detail)

    await user.click(screen.getByRole("button", { name: "Copy JSON" }))

    expect(writeText).toHaveBeenCalledWith(JSON.stringify(detail, null, 2))
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Copy JSON" })).not.toBeInTheDocument()
    expect(await screen.findByText("Copied")).toBeInTheDocument()
  })

  it("copies a metadata-only trace exactly as stored, with null input and output", async () => {
    const user = userEvent.setup()
    const writeText = vi.fn(async (_text: string) => {})
    mockClipboard(writeText)
    renderDialog({ ...searchDetail(), input: null, output: null })

    await user.click(screen.getByRole("button", { name: "Copy JSON" }))

    const copied: unknown = JSON.parse(writeText.mock.calls[0]?.[0] ?? "")
    expect(copied).toMatchObject({ traceId: searchDetail().traceId, input: null, output: null })
  })

  it("keeps Copy JSON when the clipboard write fails", async () => {
    const user = userEvent.setup()
    const writeText = vi.fn(() => Promise.reject(new Error("denied")))
    mockClipboard(writeText)
    renderDialog(searchDetail())

    await user.click(screen.getByRole("button", { name: "Copy JSON" }))
    await act(async () => {})
    expect(writeText).toHaveBeenCalledTimes(1)

    expect(screen.getByRole("button", { name: "Copy JSON" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Copied" })).not.toBeInTheDocument()
    expect(screen.queryByText("Copied")).not.toBeInTheDocument()
  })

  it.each([
    ["loading", { status: "loading" }],
    ["error", { status: "error", error: "boom" }],
    ["missing", { status: "missing", error: "This trace is not available in this project." }],
  ])("offers no Copy JSON in the %s state", (_state, overrides) => {
    renderDialog(null, overrides)

    expect(screen.getByRole("dialog")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Copy JSON" })).not.toBeInTheDocument()
  })
})

/**
 * TASK-000063 initiated-by attribution: the summary rail keeps attribution
 * visible as its third cell, with human labels, key-distinct rows, and quiet
 * legacy rows carrying no project rename.
 */
describe("TraceDetailDialog actor identity", () => {
  const ACTOR_DETAIL_ID = "9".repeat(32)

  function detailWithActor(overrides: Record<string, unknown> = {}): TraceDetail {
    return mapTraceDetail(traceDetailFixture({ trace_id: ACTOR_DETAIL_ID, ...overrides }))
  }

  function railTerms(): string[] {
    const rail = document.querySelector("dl")!
    return Array.from(rail.querySelectorAll(":scope > div dt")).map(
      (term) => term.textContent ?? ""
    )
  }

  function railValues(): string[] {
    const rail = document.querySelector("dl")!
    return Array.from(rail.querySelectorAll(":scope > div dd")).map(
      (value) => value.textContent ?? ""
    )
  }

  it("keeps attribution visible as the third rail cell with the approved labels", () => {
    renderDialog(
      detailWithActor({
        actor_type: "human",
        first_name: "Ada",
        last_name: "Lovelace",
        email: "ada@example.com",
      })
    )

    expect(railTerms()).toEqual([
      "Status",
      "Provider",
      "Initiated by",
      "Total latency",
      "Results",
    ])
    expect(railValues()[2]).toBe("Ada Lovelace")
    expect(document.body.innerHTML).not.toContain("ada@example.com")
  })

  it("shows the API key name and prefix in the Initiated by cell", () => {
    renderDialog(
      detailWithActor({
        actor_type: "project_api_key",
        api_key_name: "test-key",
        api_key_prefix: "pw_live_ab12",
      })
    )

    expect(railValues()[2]).toBe("test-keyAPI key · pw_live_ab12")
  })
})

/**
 * Old backend bug: a FETCH root stored with `started_at` after `ended_at`
 * (duration 0) while its children are correct. The dialog must show the span
 * envelope, not a 0 ms total, and scale the whole timeline to it.
 */
describe("TraceDetailDialog inconsistent root timeline", () => {
  const at = (seconds: string) => `2026-10-01T10:00:${seconds}Z`
  const span = (
    id: string,
    parent: string | null,
    name: string,
    stage: string,
    start: string,
    end: string,
    ms: number,
    extra: Record<string, unknown> = {}
  ) => ({
    span_id: id.padEnd(16, "0"),
    parent_span_id: parent === null ? null : parent.padEnd(16, "0"),
    name,
    stage,
    kind: "internal",
    started_at: at(start),
    ended_at: at(end),
    duration_ms: ms,
    outcome: "success",
    error: null,
    events: [],
    ...extra,
  })

  function brokenRoot(): TraceDetail {
    return mapTraceDetail(
      traceDetailFixture({
        operation: "fetch",
        started_at: at("20.568000"),
        duration_ms: 0,
        spans: [
          span("aa", null, "POST /fetch", "Fetch request", "20.568000", "19.352000", 0, { kind: "server" }),
          span("bb", "aa", "polyweb.route", "Route selection", "18.888000", "18.922000", 34),
          span("cc", "aa", "polyweb.provider", "Provider request", "18.923000", "19.318000", 394, {
            kind: "client",
            provider: "keenable",
          }),
          span("dd", "aa", "polyweb.results", "Results", "19.351000", "19.351000", 0),
          span("ee", "aa", "polyweb.response", "Response", "19.352000", "19.352000", 1),
        ],
      })
    )
  }

  it("shows the envelope as the total latency in the header, not 0 ms", () => {
    renderDialog(brokenRoot())

    const rail = document.querySelector("dl")!
    const values = Array.from(rail.querySelectorAll(":scope > div dd")).map((value) => value.textContent)
    expect(values[3]).toBe("464 ms")
  })

  it("scales the timeline axis to the envelope and derives the phases from it", async () => {
    const user = userEvent.setup()
    renderDialog(brokenRoot())

    await user.click(screen.getByRole("button", { name: "Timeline" }))

    expect(screen.getByText("Timeline scale 0 to 464 milliseconds")).toBeInTheDocument()
    expect(screen.queryByText(/Timeline scale 0 to 1 milliseconds/)).not.toBeInTheDocument()
    const phase = (label: string) => screen.getByText(label).nextElementSibling?.textContent
    expect(phase("Before providers")).toBe("35 ms")
    expect(phase("Provider active")).toBe("394 ms")
    expect(phase("After providers")).toBe("35 ms")
    const trajectory = screen.getByRole("list", { name: "Trace trajectory" })
    // The root row spans the whole envelope; the child bars stay inside the track.
    expect(within(trajectory).getByText("464 ms")).toBeInTheDocument()
    for (const bar of trajectory.querySelectorAll<HTMLElement>("[aria-hidden='true'] > span")) {
      const left = Number.parseFloat(bar.style.left)
      const width = Number.parseFloat(bar.style.width)
      expect(left).toBeGreaterThanOrEqual(0)
      expect(left + width).toBeLessThanOrEqual(100.0001)
    }
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
    expect(rail?.querySelectorAll(":scope > div")).toHaveLength(5)
    expect(
      Array.from(rail?.querySelectorAll(":scope > div dt") ?? []).map(
        (term) => term.textContent
      )
    ).toEqual(["Status", "Provider", "Initiated by", "Total latency", "Results"])
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
