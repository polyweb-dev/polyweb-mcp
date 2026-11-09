import { describe, expect, it, afterEach, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes, useLocation } from "react-router"
import { ProjectScopeContext } from "@/domains/projects/state/context"
import { PROJECT_ALPHA_ID, projectScopeValue } from "@/test/accessFixtures"
import { mapTraceDetail, mapTraceList } from "@/domains/activity"
import type { TraceSummary } from "@/domains/activity"
import { ActivityList } from "./ActivityList"
import { ActivityPage } from "./ActivityPage"
import { formatDateTime } from "@/shared/lib/formatTime"
import { deferred, err, installFetchStub, ok } from "@/test/fetchMock"
import {
  AGGREGATED_TRACE_ID,
  ERROR_TRACE_ID,
  SUCCESS_TRACE_ID,
  aggregatedTraceDetailFixture,
  traceDetailFixture,
  traceListFixture,
  traceSummaryFixture,
} from "@/test/fixtures/activity"

const TRACES = `/api/v1/projects/${PROJECT_ALPHA_ID}/traces`
const TRACE_LIST_RE = /^\/api\/v1\/projects\/[^/]+\/traces(\?|$)/
const TRACE_DETAIL_RE = /^\/api\/v1\/projects\/[^/]+\/traces\//

function LocationProbe() {
  const location = useLocation()
  return <p data-testid="location-probe">{`${location.pathname}${location.search}`}</p>
}

/** Render the Activity page of the alpha project at one query string. */
function renderActivityPage(search = "") {
  return render(
    <MemoryRouter initialEntries={[`/p/${PROJECT_ALPHA_ID}/activity${search}`]}>
      <ProjectScopeContext.Provider value={projectScopeValue()}>
        <Routes>
          <Route path="/p/:projectId/activity" element={<ActivityPage />} />
        </Routes>
        <LocationProbe />
      </ProjectScopeContext.Provider>
    </MemoryRouter>
  )
}

/**
 * The Activity list is a scannable, payload-free table: seven headers ending
 * in Actions, one shared "View details" chevron button per row, and
 * never the query or result URLs in the list document. An aggregated fanout
 * row discloses one nested provider attempt per recorded call. Page-level
 * loading, error, empty, and filter states live in ActivityPage and are locked
 * in below.
 */
function summaries(): TraceSummary[] {
  return mapTraceList(traceListFixture())
}

/**
 * One latency cell in the shared format: `3,381 ms` (thousands separator and
 * a space before the unit), also accepting the older `3381ms`.
 */
function ms(value: number): RegExp {
  return new RegExp(`^${value.toLocaleString("en-US").replace(",", ",?")} ?ms$`)
}

function listProps(overrides = {}) {
  return {
    summaries: summaries(),
    expandedTraceId: null,
    detailsById: {},
    onSelect: vi.fn(),
    onToggleProviders: vi.fn(),
    onInspect: vi.fn(),
    onRetry: vi.fn(),
    ...overrides,
  }
}

describe("ActivityList", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("renders seven visible headers ending in Actions", () => {
    render(<ActivityList {...listProps()} />)

    const headers = screen.getAllByRole("columnheader")
    expect(headers.map((header) => header.textContent)).toEqual([
      "Time",
      "Operation",
      "Provider",
      "Status",
      "Latency",
      "Results",
      "Actions",
    ])
  })

  it("renders one payload-free row per trace before expansion", () => {
    render(<ActivityList {...listProps()} />)

    const rows = screen.getAllByRole("row")
    // Header row plus one row per trace (aggregated + search + fetch).
    expect(rows).toHaveLength(4)
    const body = document.body.textContent ?? ""
    expect(body).not.toContain("What is the latest financial news?")
    expect(body).not.toContain("distributed consensus algorithms")
    expect(body).not.toContain("https://docs.freesearch.dev/consensus")
    expect(body).not.toContain("https://docs.freesearch.dev/getting-started")
    expect(body).not.toContain("Raft, Paxos")
  })

  it("renders one shared icon button per row instead of repeated text buttons", () => {
    render(<ActivityList {...listProps()} />)

    const buttons = screen.getAllByRole("button", { name: "View details" })
    expect(buttons).toHaveLength(3)
    for (const button of buttons) {
      expect(button.tagName.toLowerCase()).toBe("button")
      expect(button).toHaveAttribute("data-slot", "button")
      // The chevron carries the name; no visible "View details" text repeats per row.
      expect(button.textContent?.trim()).toBe("")
    }
  })

  it("renders on the shared fs-table instead of the table primitive", () => {
    render(<ActivityList {...listProps()} />)

    const table = screen.getByRole("table", { name: "Activity" })
    expect(table).toHaveClass("fs-table")
    expect(document.querySelector('[data-slot="table"]')).toBeNull()
  })

  it("shows latency and result counts without inventing values", () => {
    render(<ActivityList {...listProps()} />)

    expect(screen.getByText(ms(3381))).toBeInTheDocument()
    expect(screen.getByText(ms(248))).toBeInTheDocument()
    expect(screen.getByText(ms(512))).toBeInTheDocument()
    expect(screen.getByText("6")).toBeInTheDocument()
    expect(screen.getByText("2")).toBeInTheDocument()
  })

  it("shows relative times with the exact timestamp on hover", () => {
    const now = Date.now()
    const startedAt = new Date(now - 86_400_000).toISOString()
    render(<ActivityList {...listProps({ summaries: [{ ...summaries()[0]!, startedAt }] })} />)

    expect(screen.getByText("1 d ago")).toHaveAttribute("title", formatDateTime(startedAt))
  })

  it("labels the aggregated row All providers with an accessible expander", () => {
    const onToggleProviders = vi.fn()
    render(<ActivityList {...listProps({ onToggleProviders })} />)

    expect(screen.getByText("All providers")).toBeInTheDocument()
    const expander = screen.getByRole("button", {
      name: /Show provider responses for/,
    })
    expect(expander).toHaveAttribute("aria-expanded", "false")
    expect(expander).toHaveAttribute("aria-controls", `trace-providers-${AGGREGATED_TRACE_ID}`)
  })

  it("toggles provider expansion through the chevron with aria state", async () => {
    const user = userEvent.setup()
    const onToggleProviders = vi.fn()
    render(<ActivityList {...listProps({ onToggleProviders })} />)

    await user.click(
      screen.getByRole("button", { name: /Show provider responses for/ })
    )
    expect(onToggleProviders).toHaveBeenCalledTimes(1)
    expect(onToggleProviders).toHaveBeenCalledWith(AGGREGATED_TRACE_ID)
  })

  it("renders nested provider rows with status, latency, count, and View details", () => {
    const detail = mapTraceDetail(aggregatedTraceDetailFixture())
    render(
      <ActivityList
        {...listProps({
          expandedTraceId: AGGREGATED_TRACE_ID,
          detailsById: {
            [AGGREGATED_TRACE_ID]: { status: "ready", detail, error: null },
          },
        })}
      />
    )

    // R6 unifies the action text: 3 parent rows plus 7 nested provider rows.
    expect(screen.getAllByRole("button", { name: "View details" })).toHaveLength(10)
    const inspectButtons = [2025, 3223, 1450, 1780, 2050, 2310, 830].map(
      (latency) => within(screen.getByText(ms(latency)).closest("tr")!).getByRole("button", { name: "View details" })
    )
    expect(inspectButtons).toHaveLength(7)
    // Scope by the attempt latency: the parent list has other Keenable rows.
    const keenableRow = screen.getByText(ms(2025)).closest("tr")!
    expect(within(keenableRow).getByText("Keenable")).toBeInTheDocument()
    expect(within(keenableRow).getByText("3")).toBeInTheDocument()
    expect(within(keenableRow).getByText("Success")).toBeInTheDocument()
    const tavilyRow = screen.getByText(ms(3223)).closest("tr")!
    expect(within(tavilyRow).getByText("Tavily")).toBeInTheDocument()
  })

  it("passes the trace id and provider span id when View details is clicked", async () => {
    const user = userEvent.setup()
    const onInspect = vi.fn()
    const detail = mapTraceDetail(aggregatedTraceDetailFixture())
    render(
      <ActivityList
        {...listProps({
          expandedTraceId: AGGREGATED_TRACE_ID,
          detailsById: {
            [AGGREGATED_TRACE_ID]: { status: "ready", detail, error: null },
          },
          onInspect,
        })}
      />
    )

    const keenableRow = screen.getByText(ms(2025)).closest("tr")!
    await user.click(within(keenableRow).getByRole("button", { name: "View details" }))

    expect(onInspect).toHaveBeenCalledTimes(1)
    expect(onInspect).toHaveBeenCalledWith(AGGREGATED_TRACE_ID, "a100000000000003")
  })

  it("shows loading, error with retry, and empty-attempt states in the child panel", async () => {
    const user = userEvent.setup()
    const onRetry = vi.fn()
    const { rerender } = render(
      <ActivityList
        {...listProps({ expandedTraceId: AGGREGATED_TRACE_ID, onRetry })}
      />
    )
    expect(screen.getByRole("status")).toHaveTextContent(/loading provider responses/i)

    rerender(
      <ActivityList
        {...listProps({
          expandedTraceId: AGGREGATED_TRACE_ID,
          detailsById: {
            [AGGREGATED_TRACE_ID]: { status: "error", detail: null, error: "boom" },
          },
          onRetry,
        })}
      />
    )
    expect(screen.getByRole("alert")).toHaveTextContent(/provider responses unavailable/i)
    await user.click(screen.getByRole("button", { name: "Retry" }))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it("marks unnamed provider attempts instead of guessing", () => {
    const detail = mapTraceDetail(
      aggregatedTraceDetailFixture({ provider: "aggregated" })
    )
    // Strip response results AND direct span identity so no evidence names the providers.
    const stripped = {
      ...detail,
      stages: detail.stages.map((stage) =>
        stage.name === "freesearch.provider"
          ? { ...stage, providerId: null, events: [] }
          : stage
      ),
    }
    render(
      <ActivityList
        {...listProps({
          expandedTraceId: AGGREGATED_TRACE_ID,
          detailsById: {
            [AGGREGATED_TRACE_ID]: { status: "ready", detail: stripped, error: null },
          },
        })}
      />
    )

    expect(screen.getByText("Provider attempt 1")).toBeInTheDocument()
    expect(screen.getAllByText("Name not recorded")).toHaveLength(7)
  })

  it("notifies the parent with the trace id when View details is clicked", async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    render(<ActivityList {...listProps({ onSelect })} />)

    const buttons = screen.getAllByRole("button", { name: "View details" })
    expect(buttons).toHaveLength(3)
    await user.click(buttons[0]!)

    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect).toHaveBeenCalledWith(AGGREGATED_TRACE_ID)
  })

  it("reaches View details by keyboard alone", async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    render(<ActivityList {...listProps({ onSelect })} />)

    const firstButton = screen.getAllByRole("button", { name: "View details" })[0]!
    firstButton.focus()
    expect(firstButton).toHaveFocus()
    await user.keyboard("{Enter}")

    expect(onSelect).toHaveBeenCalledWith(AGGREGATED_TRACE_ID)
  })

  it("selects the trace when its row is clicked (convenience target)", async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    render(<ActivityList {...listProps({ onSelect })} />)

    const rows = screen.getAllByRole("row")
    await user.click(rows[1]!)

    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect).toHaveBeenCalledWith(AGGREGATED_TRACE_ID)
  })

  it("selects once when the View details button is clicked inside its row", async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    render(<ActivityList {...listProps({ onSelect })} />)

    await user.click(screen.getAllByRole("button", { name: "View details" })[2]!)

    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect).toHaveBeenCalledWith(ERROR_TRACE_ID)
  })
})

/** Page-level list states: loading, error, empty, and the operation filter. */
describe("ActivityPage list states", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function stubActivity(listPayload: unknown = traceListFixture()) {
    return installFetchStub((req) => {
      if (req.method === "GET" && TRACE_DETAIL_RE.test(req.url)) {
        const traceId = decodeURIComponent(req.url.split("/").pop() ?? "")
        if (traceId === AGGREGATED_TRACE_ID) return ok(aggregatedTraceDetailFixture())
        return ok(traceDetailFixture())
      }
      if (req.method === "GET" && TRACE_LIST_RE.test(req.url)) {
        return ok(listPayload)
      }
      return err(404, { detail: "unhandled test route" })
    })
  }

  it("shows a loading state while traces are in flight", () => {
    const gate = deferred<Response>()
    installFetchStub((req) => {
      if (req.method === "GET" && TRACE_LIST_RE.test(req.url)) {
        return gate.promise
      }
      return err(404, { detail: "unhandled test route" })
    })
    renderActivityPage()

    expect(screen.getByRole("status")).toHaveTextContent(/loading activity/i)
    gate.resolve(ok(traceListFixture()))
  })

  it("shows an error state with retry when the list fails", async () => {
    installFetchStub((req) => {
      if (req.method === "GET" && TRACE_LIST_RE.test(req.url)) {
        return err(503, { detail: "traces unavailable" })
      }
      return err(404, { detail: "unhandled test route" })
    })
    renderActivityPage()

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/traces unavailable/i)
    })
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument()
  })

  it("shows an empty state when no traces were recorded", async () => {
    stubActivity({ items: [], generated_at: "2026-09-29T09:25:00.000000Z" })
    renderActivityPage()

    await waitFor(() => {
      expect(screen.getByText(/no traces recorded yet/i)).toBeInTheDocument()
    })
    expect(screen.queryByRole("table")).not.toBeInTheDocument()
  })

  it("filters the list through the Search/Fetch segmented control", async () => {
    const stub = stubActivity()
    const user = userEvent.setup()
    renderActivityPage()

    await waitFor(() => {
      expect(screen.getAllByText("Keenable").length).toBeGreaterThan(0)
    })
    const group = screen.getByRole("group", { name: "Operation" })
    expect(
      within(group).getByRole("button", { name: "All" }).getAttribute("aria-pressed")
    ).toBe("true")

    await user.click(within(group).getByRole("button", { name: "Fetch" }))
    await waitFor(() => {
      expect(
        stub.requestsTo(`${TRACES}?limit=50&operation=fetch`)
      ).toHaveLength(1)
    })

    await user.click(within(group).getByRole("button", { name: "Search" }))
    await waitFor(() => {
      expect(
        stub.requestsTo(`${TRACES}?limit=50&operation=search`)
      ).toHaveLength(1)
    })
  })

  it("keeps the success trace selectable after the fixture grew to three rows", async () => {
    stubActivity()
    const user = userEvent.setup()
    renderActivityPage()

    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: "View details" })).toHaveLength(3)
    })
    await user.click(screen.getAllByRole("button", { name: "View details" })[1]!)
    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeInTheDocument()
    })
    expect(screen.getByText("distributed consensus algorithms")).toBeInTheDocument()
    expect(SUCCESS_TRACE_ID).toContain("e1c2")
  })

  it("holds Operation and Outcome in the URL query and reloads page one", async () => {
    const stub = stubActivity()
    const user = userEvent.setup()
    renderActivityPage("?operation=fetch")

    await waitFor(() => {
      expect(stub.requestsTo(`${TRACES}?limit=50&operation=fetch`)).toHaveLength(1)
    })
    const outcome = screen.getByRole("group", { name: "Outcome" })
    expect(
      within(outcome)
        .getAllByRole("button")
        .map((button) => button.textContent)
    ).toEqual(["All", "Success", "Partial", "Error"])

    await user.click(within(outcome).getByRole("button", { name: "Error" }))
    await waitFor(() => {
      expect(stub.requestsTo(`${TRACES}?limit=50&operation=fetch&outcome=error`)).toHaveLength(1)
    })
    expect(screen.getByTestId("location-probe")).toHaveTextContent(
      `/p/${PROJECT_ALPHA_ID}/activity?operation=fetch&outcome=error`
    )
  })

  it("appends the next page with Load more and keeps the rows after the detail closes", async () => {
    const stub = installFetchStub((req) => {
      if (req.method === "GET" && TRACE_DETAIL_RE.test(req.url)) return ok(traceDetailFixture())
      if (req.method === "GET" && TRACE_LIST_RE.test(req.url)) {
        if (!req.url.includes("cursor=")) return ok(traceListFixture({ next_cursor: "page-2" }))
        return ok({
          items: [{ ...traceSummaryFixture(), trace_id: "f".repeat(32) }],
          generated_at: "2026-09-29T09:25:00.000000Z",
          next_cursor: null,
        })
      }
      return err(404, { detail: "unhandled test route" })
    })
    const user = userEvent.setup()
    renderActivityPage()

    await user.click(await screen.findByRole("button", { name: "Load more" }))
    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: "View details" })).toHaveLength(4)
    })
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument()
    // The footer states how many traces are loaded, with no "more" once the cursor ends.
    expect(screen.getByText("Showing 4 traces")).toBeInTheDocument()
    expect(stub.requestsTo(`${TRACES}?limit=50&cursor=page-2`)).toHaveLength(1)

    await user.click(screen.getAllByRole("button", { name: "View details" })[1]!)
    await screen.findByRole("dialog")
    await user.keyboard("{Escape}")
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    })
    expect(screen.getAllByRole("button", { name: "View details" })).toHaveLength(4)
  })
})

/**
 * Seven deterministic provider attempts resolve from the direct
 * `span.provider` field, including the failed `parallel` attempt
 * and the empty `exa`/`youcom` responses.
 */
describe("ActivityList seven-provider direct identity", () => {
  function expandedSeven() {
    const detail = mapTraceDetail(aggregatedTraceDetailFixture())
    return render(
      <ActivityList
        {...listProps({
          expandedTraceId: AGGREGATED_TRACE_ID,
          detailsById: {
            [AGGREGATED_TRACE_ID]: { status: "ready", detail, error: null },
          },
        })}
      />
    )
  }

  it("renders seven named provider rows from the direct span fields", () => {
    expandedSeven()

    expect(screen.getAllByRole("button", { name: "View details" })).toHaveLength(10)
    // Scope each name by its attempt latency: the parent list has other
    // provider rows (e.g. the single-provider Keenable trace).
    const expected: Array<[string, number]> = [
      ["Brave Search", 1450],
      ["Keenable", 2025],
      ["Tavily", 3223],
      ["Exa", 1780],
      ["Firecrawl", 2050],
      ["You.com", 2310],
      ["Parallel", 830],
    ]
    for (const [name, latency] of expected) {
      const row = screen.getByText(ms(latency)).closest("tr")!
      expect(within(row).getByText(name)).toBeInTheDocument()
    }
    expect(screen.queryByText(/Provider attempt/)).not.toBeInTheDocument()
    expect(screen.queryByText("Name not recorded")).not.toBeInTheDocument()
  })

  it("names the failed parallel attempt instead of leaving it unnamed", () => {
    expandedSeven()

    const parallelRow = screen.getByText(ms(830)).closest("tr")!
    expect(within(parallelRow).getByText("Parallel")).toBeInTheDocument()
    expect(within(parallelRow).getByText("Error")).toBeInTheDocument()
  })

  it("names the empty exa/youcom responses that still carry provider", () => {
    expandedSeven()

    const exaRow = screen.getByText(ms(1780)).closest("tr")!
    expect(within(exaRow).getByText("Exa")).toBeInTheDocument()
    const youcomRow = screen.getByText(ms(2310)).closest("tr")!
    expect(within(youcomRow).getByText("You.com")).toBeInTheDocument()
  })

  it("shows a logo followed by the catalog name in every provider row", () => {
    expandedSeven()

    const braveRow = screen.getByText(ms(1450)).closest("tr")!
    expect(within(braveRow).getByText("Brave Search")).toBeInTheDocument()
    expect(within(braveRow).getByTestId("provider-logo-brave")).toBeInTheDocument()
    const youcomRow = screen.getByText(ms(2310)).closest("tr")!
    expect(within(youcomRow).getByText("You.com")).toBeInTheDocument()
    expect(within(youcomRow).getByTestId("provider-logo-youcom")).toBeInTheDocument()
  })

  it("labels parent and provider actions with one View details text", () => {
    expandedSeven()

    expect(screen.getAllByRole("button", { name: "View details" })).toHaveLength(10)
    expect(screen.queryByRole("button", { name: "Inspect" })).not.toBeInTheDocument()
  })
})
