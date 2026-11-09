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
})
