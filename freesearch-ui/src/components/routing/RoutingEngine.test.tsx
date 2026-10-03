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

  it("R1: header cluster deleted — no page-level failover/count claims (bar owns status)", async () => {
    renderRouting()
    // Wait for a loaded proof (strategy cards need providers + routing config)
    // so absence is a real deletion signal, not a loading artifact.
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /^Strict priority/ })).toBeInTheDocument()
    })
    expect(screen.queryByText("Failover active", { exact: true })).toBeNull()
    expect(screen.queryByText("Failover inactive", { exact: true })).toBeNull()
    expect(screen.queryByText(/\d+ of \d+ providers eligible/)).toBeNull()
    expect(screen.queryByText(/Fallback/)).toBeNull()
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
    // 8 search-capable providers + header row (all backend rows enabled)
    expect(within(table).getAllByRole("row")).toHaveLength(9)

    await user.click(screen.getByRole("button", { name: /^Fetch$/ }))
    // 7 fetch-capable (keenable, tavily, exa, firecrawl, youcom, parallel, tinyfish) + header
    expect(within(table).getAllByRole("row")).toHaveLength(8)
    // S1: Parallel is fetch-capable via plain includes("fetch"); Brave stays fetch-incapable.
    expect(
      within(table).getByRole("row", { name: /Parallel/ })
    ).toBeInTheDocument()
    expect(
      within(table).queryByRole("row", { name: /Brave Search/ })
    ).not.toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: /^Search$/ }))
    expect(within(table).getAllByRole("row")).toHaveLength(9)
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
    // R1: header cluster deleted — claims stay absent after resolve too.
    // Status lives in the bottom StatusBar (covered by StatusBar.r1).
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /^Strict priority/ })).toBeInTheDocument()
    })
    expect(screen.queryByText("Failover active", { exact: true })).toBeNull()
    expect(screen.queryByText("Failover inactive", { exact: true })).toBeNull()
    expect(screen.queryByText(/\d+ of \d+ providers eligible/)).toBeNull()
  })
})
