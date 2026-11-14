import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { formatDateTime } from "@/shared/lib/formatTime"
import { installFetchStub, ok } from "@/test/fetchMock"
import { traceListFixture, traceSummaryFixture } from "@/test/fixtures/activity"
import { OverviewRecentActivity } from "./OverviewRecentActivity"

describe("OverviewRecentActivity", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("shows relative times with exact timestamps and formatted latency", async () => {
    const startedAt = new Date(Date.now() - 86_400_000).toISOString()
    const fixture = traceListFixture()
    installFetchStub(() => ok({
      ...fixture,
      items: [{ ...traceSummaryFixture(), started_at: startedAt, duration_ms: 1531 }],
    }))
    render(<MemoryRouter><OverviewRecentActivity accountId="a" projectId="p" /></MemoryRouter>)

    const table = await screen.findByRole("table", { name: "Recent activity" })
    expect(within(table).getByText("1 d ago")).toHaveAttribute("title", formatDateTime(startedAt))
    expect(within(table).getByText("1,531 ms")).toBeInTheDocument()
  })

  it("orders Initiated by between Provider and Status in the recent table", async () => {
    installFetchStub(() => ok(traceListFixture()))
    render(<MemoryRouter><OverviewRecentActivity accountId="a" projectId="p" /></MemoryRouter>)

    const table = await screen.findByRole("table", { name: "Recent activity" })
    const headers = within(table).getAllByRole("columnheader").map((header) => header.textContent)
    expect(headers).toEqual([
      "Time",
      "Operation",
      "Provider",
      "Initiated by",
      "Status",
      "Latency",
    ])
  })
})

/**
 * Overview attribution: visible human display names only (never an email),
 * API-key rows with key name and prefix, and quiet legacy rows without
 * renaming any project content.
 */
describe("OverviewRecentActivity actor identity", () => {
  afterEach(() => vi.unstubAllGlobals())

  const HUMAN_TRACE_ID = "4".repeat(32)
  const KEY_TRACE_ID = "5".repeat(32)
  const LEGACY_TRACE_ID = "6".repeat(32)

  function stubRows(items: Record<string, unknown>[]) {
    installFetchStub(() => ok({ items, generated_at: "2026-09-29T09:25:00.000000Z" }))
    return render(<MemoryRouter><OverviewRecentActivity accountId="a" projectId="p" /></MemoryRouter>)
  }

  function stubActorRows() {
    return stubRows([
      traceSummaryFixture({
        trace_id: HUMAN_TRACE_ID,
        first_name: "Ada",
        last_name: "Lovelace",
        username: "ada",
        // An older backend may still send an email; it must never be rendered.
        email: "ada@example.com",
      }),
      traceSummaryFixture({
        trace_id: KEY_TRACE_ID,
        actor_type: "project_api_key",
        api_key_name: "test-key",
        api_key_prefix: "pw_live_ab12",
        username: "ada",
        first_name: "Ada",
        last_name: "Lovelace",
        email: "ada@example.com",
      }),
      traceSummaryFixture({ trace_id: LEGACY_TRACE_ID }),
    ])
  }

  it("shows each actor name in the Initiated by cell of its own recent row", async () => {
    stubActorRows()

    const table = await screen.findByRole("table", { name: "Recent activity" })
    const rows = within(table).getAllByRole("row").slice(1)
    expect(within(rows[0]!).getAllByRole("cell")[3]).toHaveTextContent("Ada Lovelace")
    expect(within(rows[1]!).getAllByRole("cell")[3]).toHaveTextContent("test-key")
    // The legacy row has no name to show, so its actor context stays an em dash.
    expect(within(rows[2]!).getAllByRole("cell")[3]).toHaveTextContent("—")
    expect(screen.getByText("Ada Lovelace")).not.toBe(screen.getByText("test-key"))
  })

  it("shows the API key name with a muted `API key · prefix` line", async () => {
    stubActorRows()

    const table = await screen.findByRole("table", { name: "Recent activity" })
    const keyCell = within(within(table).getAllByRole("row")[2]!).getAllByRole("cell")[3]!
    expect(keyCell).toHaveTextContent("test-keyAPI key · pw_live_ab12")
    expect(within(keyCell).getByText("pw_live_ab12")).toHaveClass("font-mono")
  })

  it("falls back to the plain API key label when the key name is null", async () => {
    stubRows([
      traceSummaryFixture({
        trace_id: KEY_TRACE_ID,
        actor_type: "project_api_key",
        api_key_name: null,
        api_key_prefix: null,
      }),
    ])

    const table = await screen.findByRole("table", { name: "Recent activity" })
    const cell = within(within(table).getAllByRole("row")[1]!).getAllByRole("cell")[3]!
    expect(cell).toHaveTextContent(/^API key$/)
  })

  it("keeps API-key rows key-identified when stray human profile values arrive", async () => {
    stubActorRows()

    await screen.findByRole("table", { name: "Recent activity" })
    const keyRow = screen.getByText("test-key").closest("tr")!
    expect(keyRow?.textContent).not.toContain("Ada Lovelace")
    expect(keyRow?.textContent).not.toContain("ada@example.com")
  })

  it("never renders an email, even when the payload still carries one", async () => {
    const { container } = stubActorRows()

    await screen.findByRole("table", { name: "Recent activity" })
    expect(container.innerHTML).not.toContain("ada@example.com")
  })

  it("never renders an actor name as the provider name", async () => {
    stubActorRows()

    const table = await screen.findByRole("table", { name: "Recent activity" })
    expect(table).toBeInTheDocument()
    for (const name of ["Ada Lovelace", "test-key"]) {
      const row = screen.getByText(name).closest("tr")!
      const cells = within(row).getAllByRole("cell")
      expect(cells[2]).toHaveTextContent("Keenable")
      expect(cells[2]?.textContent).not.toContain(name)
      expect(cells[3]).toHaveTextContent(name)
      expect(cells[3]?.textContent).not.toContain("Keenable")
    }
  })

  it("keeps legacy missing payload rows quiet without naming a project", async () => {
    stubActorRows()

    const table = await screen.findByRole("table", { name: "Recent activity" })
    const legacyRow = within(table).getAllByRole("row").slice(1)[2]!
    expect(legacyRow.textContent).not.toContain("Ada Lovelace")
    expect(legacyRow.textContent).not.toContain("API key")
    expect(legacyRow.textContent).not.toContain("Alpha")
  })

  it("shows Unknown user, never the email, for a human without a name or username", async () => {
    const { container } = stubRows([
      traceSummaryFixture({
        trace_id: HUMAN_TRACE_ID,
        actor_type: "human",
        email: "ghost@example.com",
      }),
    ])

    const table = await screen.findByRole("table", { name: "Recent activity" })
    const cell = within(within(table).getAllByRole("row")[1]!).getAllByRole("cell")[3]!
    expect(cell).toHaveTextContent(/^Unknown user$/)
    expect(container.innerHTML).not.toContain("ghost@example.com")
  })

  it("shows two same-name humans by name only, with no email to tell them apart", async () => {
    const { container } = stubRows([
      traceSummaryFixture({
        trace_id: "7".repeat(32),
        first_name: "Ada",
        last_name: "Lovelace",
        email: "ada-one@example.com",
      }),
      traceSummaryFixture({
        trace_id: "8".repeat(32),
        first_name: "Ada",
        last_name: "Lovelace",
        email: "ada-two@example.com",
      }),
    ])

    await screen.findByRole("table", { name: "Recent activity" })
    expect(screen.getAllByText("Ada Lovelace")).toHaveLength(2)
    expect(container.innerHTML).not.toContain("@example.com")
  })
})
