import React from "react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { act, fireEvent, render, screen, within, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { useFreeSearch } from "@/context/useFreeSearch"
import { RoutingEngine } from "./RoutingEngine"
import { installFetchStub, ok, err, deferred } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
  type WireProviderStatus,
} from "@/test/backendFixtures"

/**
 * RED update: providers arrive from the live backend (mocked fetch), the
 * route simulator derives SYNCHRONOUSLY (no 250ms setTimeout — the pipeline
 * appears immediately after click), and the invented "3,000 ms" hop-timeout
 * copy is gone from resilience controls.
 */
function RoutingPresetProbe() {
  const { routingPreset } = useFreeSearch()
  return <output data-testid="routing-preset">{routingPreset}</output>
}

function renderRouting(
  providers: WireProviderStatus[] = allProvidersFixture(),
  withProbe = false,
  routingHandler?: () => Response
) {
  const stub = installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") return ok(providers)
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return routingHandler ? routingHandler() : ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    if (req.method === "PUT" && req.url === "/api/v1/routing/config") {
      return ok({ ...routingConfigFixture(), ...((req.body as object) ?? {}) })
    }
    return err(404, { detail: "unhandled test route" })
  })
  const view = render(
    <FreeSearchProvider>
      <RoutingEngine />
      {withProbe && <RoutingPresetProbe />}
    </FreeSearchProvider>
  )
  return { stub, ...view }
}

async function openSimulator() {
  await waitFor(() => {
    expect(screen.getByRole("tab", { name: /^Simulator$/ })).toBeInTheDocument()
  })
  fireEvent.click(screen.getByRole("tab", { name: /^Simulator$/ }))
}

describe("RoutingEngine (live backend)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("renders the four routing sub-tabs", async () => {
    renderRouting()
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /^Routing$/ })).toBeInTheDocument()
    })
    expect(screen.getAllByRole("tab")).toHaveLength(4)
    for (const label of ["Strategy", "Simulator", "Ranks", "Resilience"]) {
      expect(screen.getByRole("tab", { name: new RegExp(`^${label}$`) })).toBeInTheDocument()
    }
  })

  it("reports eligibility with backend-tolerant counts", async () => {
    renderRouting()
    await waitFor(() => {
      expect(screen.getByText(/Failover active/)).toBeInTheDocument()
    })
    expect(screen.getByText(/\d+ of \d+ providers eligible/)).toBeInTheDocument()
    const activeStatus = screen.getByText("Failover active", { exact: true })
    const statusRegion = activeStatus.parentElement?.parentElement ?? activeStatus
    expect(statusRegion.textContent).not.toContain("·")
  })

  it("updates the routing preset when a strategy card is selected", async () => {
    const user = userEvent.setup()
    renderRouting(allProvidersFixture(), true)
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /^Latency optimized/ })).toBeInTheDocument()
    })

    await user.click(screen.getByRole("button", { name: /^Latency optimized/ }))

    expect(screen.getByTestId("routing-preset")).toHaveTextContent("latency_optimized")
  })

  it("derives the simulation synchronously with no timer wait", async () => {
    renderRouting()
    await openSimulator()

    const input = screen.getByPlaceholderText("Type simulated query...", { exact: true })
    fireEvent.change(input, { target: { value: "distributed systems benchmarks" } })
    // SYNCHRONOUS derive: visible immediately after click, no waitFor/timers.
    fireEvent.click(screen.getByRole("button", { name: /^Simulate route$/ }))

    expect(screen.getByText("Client Ingress", { exact: true })).toBeInTheDocument()
    expect(screen.getByText("Brave Search", { exact: true })).toBeInTheDocument()
    expect(screen.getByText(/Failover cascade/i)).toBeInTheDocument()
  })

  it("renders an explicit empty state when no providers are eligible", async () => {
    const disabled = allProvidersFixture().map((p) => ({ ...p, enabled: false }))
    renderRouting(disabled as WireProviderStatus[])
    await openSimulator()

    expect(screen.getByText(/no eligible providers/i)).toBeInTheDocument()
    expect(screen.queryByText("Client Ingress", { exact: true })).not.toBeInTheDocument()
  })

  it("filters the ranks table by operation", async () => {
    const user = userEvent.setup()
    renderRouting()
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: /^Ranks$/ })).toBeInTheDocument()
    })
    await user.click(screen.getByRole("tab", { name: /^Ranks$/ }))

    const table = screen.getByRole("table")
    // 7 search-capable providers + header row (all backend rows enabled)
    expect(within(table).getAllByRole("row")).toHaveLength(8)

    await user.click(screen.getByRole("button", { name: /^Fetch$/ }))
    // 4 fetch-capable (keenable, tavily, firecrawl, youcom) + header
    expect(within(table).getAllByRole("row")).toHaveLength(5)

    await user.click(screen.getByRole("button", { name: /^Search$/ }))
    expect(within(table).getAllByRole("row")).toHaveLength(8)
    const filter = screen.getByRole("textbox")
    await user.clear(filter)
    await user.type(filter, "Keenable")
    expect(within(table).getAllByRole("row")).toHaveLength(2)
  })

  it("preserves true rank and role when provider ranks are filtered", async () => {
    const user = userEvent.setup()
    renderRouting()
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: /^Ranks$/ })).toBeInTheDocument()
    })
    await user.click(screen.getByRole("tab", { name: /^Ranks$/ }))

    const table = screen.getByRole("table")
    expect(
      within(table).getByRole("row", { name: /#1.*Brave Search.*Primary/ })
    ).toBeInTheDocument()
    expect(
      within(table).getByRole("row", { name: /#2.*Keenable.*Fallback/ })
    ).toBeInTheDocument()

    const filter = screen.getByRole("textbox")
    await user.clear(filter)
    await user.type(filter, "Keenable")

    expect(
      within(table).getByRole("row", { name: /#2.*Keenable.*Fallback/ })
    ).toBeInTheDocument()
    expect(
      within(table).queryByRole("row", { name: /#1.*Keenable.*Primary/ })
    ).not.toBeInTheDocument()
  })

  it("renders resilience depth with NO invented timeout budget", async () => {
    const user = userEvent.setup()
    renderRouting()
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: /^Resilience$/ })).toBeInTheDocument()
    })
    await user.click(screen.getByRole("tab", { name: /^Resilience$/ }))

    expect(screen.getByText("Cascade depth", { exact: true })).toBeInTheDocument()
    // The honest backend has no per-hop timeout to display: invented copy is gone.
    expect(screen.queryByText("3,000 ms", { exact: true })).not.toBeInTheDocument()
    // The auto-bypass row was deleted: no such claim may render.
    expect(screen.queryByText("Circuit breaker auto-bypass")).toBeNull()
  })

  it("PUTs free_first once when the cost-optimized card is selected", async () => {
    const user = userEvent.setup()
    const { stub } = renderRouting()
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /^Cost optimized/ })
      ).toBeInTheDocument()
    })

    await user.click(screen.getByRole("button", { name: /^Cost optimized/ }))

    await waitFor(() => {
      const puts = stub.requests.filter(
        (r) => r.method === "PUT" && r.url === "/api/v1/routing/config"
      )
      expect(puts).toHaveLength(1)
    })
    const puts = stub.requests.filter(
      (r) => r.method === "PUT" && r.url === "/api/v1/routing/config"
    )
    expect(puts[0].body).toMatchObject({ cost_optimization_preset: "free_first" })
  })

  it("marks non-cost strategies as simulation-only and drops the applies-to-all subtitle", async () => {
    renderRouting()
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /^Strict priority/ })
      ).toBeInTheDocument()
    })

    expect(screen.queryByText("Applies to every resolved route")).toBeNull()
    for (const label of ["Strict priority", "Latency optimized", "Quality first"]) {
      const card = screen.getByRole("button", { name: new RegExp(`^${label}`) })
      expect(
        within(card).getByText(/simulation view only|simulation only|preview only/i)
      ).toBeInTheDocument()
    }
  })

  it("renders the persistent routingError and hides failover claims while errored", async () => {
    renderRouting(allProvidersFixture(), false, () =>
      err(500, { detail: "routing store down" })
    )

    await waitFor(
      () => {
        expect(screen.getByText(/routing store down/i)).toBeInTheDocument()
      },
      { timeout: 5000 }
    )
    expect(screen.queryByText("Failover active", { exact: true })).toBeNull()
    expect(screen.queryByText("Failover inactive", { exact: true })).toBeNull()
  })

  it("hides failover claims while routing is still loading", async () => {
    const gate = deferred<Response>()
    installFetchStub((req) => {
      if (req.url === "/api/v1/providers" && req.method === "GET") {
        return ok(allProvidersFixture())
      }
      if (req.url === "/api/v1/routing/config" && req.method === "GET") {
        return gate.promise as unknown as Response
      }
      if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
      return err(404, { detail: "unhandled test route" })
    })
    render(
      <FreeSearchProvider>
        <RoutingEngine />
      </FreeSearchProvider>
    )

    // While the config is in flight no failover claim may render.
    expect(screen.queryByText("Failover active", { exact: true })).toBeNull()
    expect(screen.queryByText("Failover inactive", { exact: true })).toBeNull()

    await act(async () => {
      gate.resolve(ok(routingConfigFixture()))
    })
    await waitFor(() => {
      expect(screen.getByText("Failover active", { exact: true })).toBeInTheDocument()
    })
  })
})
