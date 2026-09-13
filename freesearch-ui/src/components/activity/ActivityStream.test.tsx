import React from "react"
import { describe, expect, it, afterEach, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { FreeSearchContext } from "@/context/context"
import { ActivityStream } from "./ActivityStream"
import { installFetchStub, ok, err, deferred } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
} from "@/test/backendFixtures"
import type { UsageEvent } from "@/domains/dashboard"

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

/**
 * RF5: optimistic local events carry no unit claim (id ends "-local",
 * unitKind/displayUnit null). The ActivityStream must render them as
 * pending/— — never the "legacy" label reserved for pre-canonical rows.
 * Deterministic: events are injected via context, no fetch, no Date.now.
 */
function localEvent(overrides: Partial<UsageEvent> = {}): UsageEvent {
  return {
    id: "2026-09-06T10:02:00Z-tavily-local",
    timestamp: "2026-09-06T10:02:00Z",
    operation: "search",
    queryOrUrl: "",
    providerId: "tavily",
    providerName: "Tavily",
    latencyMs: 187,
    costCredits: 1,
    status: "success",
    routeReason: "Recorded search via tavily",
    fallbackChain: ["tavily"],
    unitKind: null,
    displayUnit: null,
    ...overrides,
  }
}

function renderActivityWithEvents(events: UsageEvent[]) {
  const value = {
    providers: [],
    providersLoading: false,
    providersError: null,
    fallbackConfig: {
      enabled: true,
      maxAttempts: 3,
      fallbackOnRateLimit: true,
      fallbackOnTimeout: true,
      fallbackOnServerError: true,
    },
    routingLoading: false,
    routingError: null,
    routingPreset: "priority",
    costOptimizationPreset: "balanced",
    activeSearch: null,
    activeFetch: null,
    isSearching: false,
    isFetching: false,
    searchError: null,
    fetchError: null,
    usageEvents: events,
    usageLoading: false,
    usageError: null,
    usageTotals: [],
    dashboardQuotas: [],
    quotaAvailable: false,
    dashboardNotice: null,
    toasts: [],
    toggleProvider: vi.fn(),
    toggleProviderSearch: vi.fn(),
    toggleProviderFetch: vi.fn(),
    updateProviderPriority: vi.fn(),
    moveProviderPriority: vi.fn(),
    setCircuitBreaker: vi.fn(),
    testProviderConnection: vi.fn(),
    saveProviderKey: vi.fn(),
    deleteProviderKey: vi.fn(),
    updateFallbackConfig: vi.fn(),
    updateCostPreset: vi.fn(),
    setRoutingPreset: vi.fn(),
    runSearch: vi.fn(),
    runFetch: vi.fn(),
    clearActiveResults: vi.fn(),
    refreshProviders: vi.fn(),
    refreshDashboard: vi.fn(),
    showToast: vi.fn(),
    dismissToast: vi.fn(),
  } as never
  return render(
    <FreeSearchContext.Provider value={value}>
      <ActivityStream />
    </FreeSearchContext.Provider>
  )
}

describe("ActivityStream RF5: optimistic -local events", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("renders a -local null-kind search event as pending/—, never 'legacy'", () => {
    renderActivityWithEvents([localEvent()])

    const row = screen.getByText("Tavily", { exact: true }).closest("tr")!
    expect(row.textContent).toMatch(/pending|—/)
    expect(row.textContent).not.toMatch(/legacy/i)
  })

  it("renders a -local null-kind fetch event as pending/—, never 'legacy'", () => {
    renderActivityWithEvents([
      localEvent({
        id: "2026-09-06T10:03:01Z-firecrawl-local",
        timestamp: "2026-09-06T10:03:01Z",
        operation: "fetch",
        providerId: "firecrawl",
        providerName: "Firecrawl",
        routeReason: "Recorded fetch via firecrawl",
        fallbackChain: ["firecrawl"],
      }),
    ])

    const row = screen.getByText("Firecrawl", { exact: true }).closest("tr")!
    expect(row.textContent).toMatch(/pending|—/)
    expect(row.textContent).not.toMatch(/legacy/i)
  })

  it("keeps the -local id suffix as the pending marker (contract for the Developer)", () => {
    const event = localEvent()
    expect(event.id.endsWith("-local")).toBe(true)
    expect(event.unitKind).toBeNull()
    expect(event.displayUnit).toBeNull()
  })
})
