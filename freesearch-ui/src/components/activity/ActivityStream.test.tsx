import React from "react"
import { describe, expect, it, afterEach, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { ActivityStream } from "./ActivityStream"
import { installFetchStub, ok, err, deferred } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
} from "@/test/backendFixtures"

/**
 * RED update: events are fed by GET /dashboard (mocked fetch) instead of
 * invented INITIAL_USAGE_EVENTS. Covers loading / error / empty states and
 * keeps the privacy contract: queryOrUrl is NEVER rendered.
 */
const operationalColumns = ["Time", "Operation", "Provider", "Status", "Latency", "Units"]

function renderWithBackend(
  dashboardHandler: (req: { url: string }) => Response = () => ok(dashboardFixture())
) {
  installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return dashboardHandler(req)
    return err(404, { detail: "unhandled test route" })
  })
  return render(
    <FreeSearchProvider>
      <ActivityStream />
    </FreeSearchProvider>
  )
}

describe("ActivityStream (live backend)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("shows a loading state while the dashboard is in flight", () => {
    const gate = deferred<Response>()
    renderWithBackend(() => gate.promise as unknown as Response)
    // Note: the stub returns the pending promise; the component must render
    // a loading indicator instead of invented rows.
    expect(screen.getByText(/loading/i)).toBeInTheDocument()
    gate.resolve(ok(dashboardFixture()))
  })

  it("renders dashboard-fed events with only the operational columns", async () => {
    renderWithBackend()
    await waitFor(() => {
      expect(screen.getByText("Tavily", { exact: true })).toBeInTheDocument()
    })

    const headers = screen.getAllByRole("columnheader")
    expect(headers).toHaveLength(operationalColumns.length)
    for (const column of operationalColumns) {
      expect(
        screen.getByRole("columnheader", { name: new RegExp(`^${column}$`) })
      ).toBeInTheDocument()
    }
    expect(
      screen.queryByRole("columnheader", { name: /^Cost$/ })
    ).not.toBeInTheDocument()
  })

  it("labels usage costs in units, never credits/cr", async () => {
    renderWithBackend()
    await waitFor(() => {
      expect(screen.getByText("Tavily", { exact: true })).toBeInTheDocument()
    })

    expect(document.body.textContent).toMatch(/units/i)
    expect(document.body.textContent).not.toMatch(/\dcr/)
  })

  it("never renders query or URL targets in the document", async () => {
    renderWithBackend()
    await waitFor(() => {
      expect(screen.getByText("Tavily", { exact: true })).toBeInTheDocument()
    })

    const body = document.body.textContent ?? ""
    expect(body).not.toContain("distributed consensus algorithms")
    expect(body).not.toContain("https://docs.freesearch.dev/getting-started")
    // Dashboard UsageEvents carry queryOrUrl: "" — nothing link-like leaks
    expect(body).not.toContain("https://example.com")
  })

  it("shows an error state when the dashboard request fails", async () => {
    renderWithBackend(() => err(503, { detail: "telemetry unavailable" }))

    await waitFor(() => {
      expect(screen.getByText(/telemetry unavailable|error|failed/i)).toBeInTheDocument()
    })
  })

  it("shows an empty state when the dashboard has no recent usage", async () => {
    renderWithBackend(() => ok(dashboardFixture({ recent_usage: [] })))

    await waitFor(() => {
      expect(screen.getByText(/no events|nothing yet|empty/i)).toBeInTheDocument()
    })
    expect(screen.queryByRole("table")).not.toBeInTheDocument()
  })

  it("does not render a Clear log action", async () => {
    renderWithBackend()
    await waitFor(() => {
      expect(screen.getByText("Tavily", { exact: true })).toBeInTheDocument()
    })

    expect(screen.queryByRole("button", { name: /^Clear log$/ })).not.toBeInTheDocument()
  })
})
