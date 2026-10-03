import { describe, expect, it, afterEach, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { mapTraceList } from "@/domains/activity"
import type { TraceSummary } from "@/domains/activity"
import { ActivityList } from "./ActivityList"
import { ActivityPage } from "./ActivityPage"
import { deferred, err, installFetchStub, ok } from "@/test/fetchMock"
import {
  ERROR_TRACE_ID,
  SUCCESS_TRACE_ID,
  traceDetailFixture,
  traceListFixture,
} from "@/test/fixtures/activity"

/**
 * The Activity list is a scannable, payload-free table: six operational
 * columns, one keyboard-reachable "View details" control per row, and never
 * the query or result URLs in the list document. Page-level loading, error,
 * empty, and filter states live in ActivityPage and are locked in below.
 */
function summaries(): TraceSummary[] {
  return mapTraceList(traceListFixture())
}

describe("ActivityList", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("renders the six operational columns plus the details action column", () => {
    render(<ActivityList summaries={summaries()} onSelect={() => {}} />)

    const headers = screen.getAllByRole("columnheader")
    expect(headers.map((header) => header.textContent)).toEqual([
      "Time",
      "Operation",
      "Provider",
      "Status",
      "Latency",
      "Results",
      "Details",
    ])
  })

  it("renders one payload-free row per trace", () => {
    render(<ActivityList summaries={summaries()} onSelect={() => {}} />)

    const rows = screen.getAllByRole("row")
    // Header row plus one row per trace.
    expect(rows).toHaveLength(3)
    const body = document.body.textContent ?? ""
    expect(body).not.toContain("distributed consensus algorithms")
    expect(body).not.toContain("https://docs.freesearch.dev/consensus")
    expect(body).not.toContain("https://docs.freesearch.dev/getting-started")
    expect(body).not.toContain("Raft, Paxos")
  })

  it("shows latency and result counts without inventing values", () => {
    render(<ActivityList summaries={summaries()} onSelect={() => {}} />)

    expect(screen.getByText("248ms")).toBeInTheDocument()
    expect(screen.getByText("512ms")).toBeInTheDocument()
    // Search trace reported 2 results; the failed fetch reports none.
    expect(screen.getByText("2")).toBeInTheDocument()
  })

  it("labels search and fetch operations as given", () => {
    render(<ActivityList summaries={summaries()} onSelect={() => {}} />)

    expect(screen.getByText("search", { exact: false })).toBeInTheDocument()
    expect(screen.getByText("fetch", { exact: false })).toBeInTheDocument()
  })

  it("renders only the rows it is given (filtering happens upstream)", () => {
    render(
      <ActivityList
        summaries={summaries().filter((summary) => summary.operation === "fetch")}
        onSelect={() => {}}
      />
    )

    expect(screen.queryByText("search", { exact: false })).not.toBeInTheDocument()
    expect(screen.getByText("fetch", { exact: false })).toBeInTheDocument()
    expect(screen.getAllByRole("button", { name: "View details" })).toHaveLength(1)
  })

  it("notifies the parent with the trace id when View details is clicked", async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    render(<ActivityList summaries={summaries()} onSelect={onSelect} />)

    const buttons = screen.getAllByRole("button", { name: "View details" })
    expect(buttons).toHaveLength(2)
    await user.click(buttons[0]!)

    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect).toHaveBeenCalledWith(SUCCESS_TRACE_ID)
  })

  it("reaches View details by keyboard alone", async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    render(<ActivityList summaries={summaries()} onSelect={onSelect} />)

    const firstButton = screen.getAllByRole("button", { name: "View details" })[0]!
    firstButton.focus()
    expect(firstButton).toHaveFocus()
    await user.keyboard("{Enter}")

    expect(onSelect).toHaveBeenCalledWith(SUCCESS_TRACE_ID)
  })

  it("selects the trace when its row is clicked (convenience target)", async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    render(<ActivityList summaries={summaries()} onSelect={onSelect} />)

    // Row 0 is the header row; row 1 is the newest trace (the search trace).
    const rows = screen.getAllByRole("row")
    await user.click(rows[1]!)

    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect).toHaveBeenCalledWith(SUCCESS_TRACE_ID)
  })

  it("selects once when the View details button is clicked inside its row", async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    render(<ActivityList summaries={summaries()} onSelect={onSelect} />)

    await user.click(screen.getAllByRole("button", { name: "View details" })[1]!)

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
      if (req.method === "GET" && req.url.startsWith("/api/v1/traces/")) {
        return ok(traceDetailFixture())
      }
      if (req.method === "GET" && req.url.startsWith("/api/v1/traces")) {
        return ok(listPayload)
      }
      return err(404, { detail: "unhandled test route" })
    })
  }

  it("shows a loading state while traces are in flight", () => {
    const gate = deferred<Response>()
    installFetchStub((req) => {
      if (req.method === "GET" && req.url.startsWith("/api/v1/traces")) {
        return gate.promise
      }
      return err(404, { detail: "unhandled test route" })
    })
    render(<ActivityPage />)

    expect(screen.getByRole("status")).toHaveTextContent(/loading activity/i)
    gate.resolve(ok(traceListFixture()))
  })

  it("shows an error state with retry when the list fails", async () => {
    installFetchStub((req) => {
      if (req.method === "GET" && req.url.startsWith("/api/v1/traces")) {
        return err(503, { detail: "traces unavailable" })
      }
      return err(404, { detail: "unhandled test route" })
    })
    render(<ActivityPage />)

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/traces unavailable/i)
    })
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument()
  })

  it("shows an empty state when no traces were recorded", async () => {
    stubActivity({ items: [], generated_at: "2026-09-29T09:25:00.000000Z" })
    render(<ActivityPage />)

    await waitFor(() => {
      expect(screen.getByText(/no traces recorded yet/i)).toBeInTheDocument()
    })
    expect(screen.queryByRole("table")).not.toBeInTheDocument()
  })

  it("filters the list through the Search/Fetch segmented control", async () => {
    const stub = stubActivity()
    const user = userEvent.setup()
    render(<ActivityPage />)

    await waitFor(() => {
      expect(screen.getAllByText("Keenable").length).toBeGreaterThan(0)
    })
    const group = screen.getByRole("group", { name: /operation filter/i })
    expect(
      within(group).getByRole("button", { name: "All" }).getAttribute("aria-pressed")
    ).toBe("true")

    await user.click(within(group).getByRole("button", { name: "Fetch" }))
    await waitFor(() => {
      expect(
        stub.requestsTo("/api/v1/traces?limit=50&operation=fetch")
      ).toHaveLength(1)
    })

    await user.click(within(group).getByRole("button", { name: "Search" }))
    await waitFor(() => {
      expect(
        stub.requestsTo("/api/v1/traces?limit=50&operation=search")
      ).toHaveLength(1)
    })
  })
})
