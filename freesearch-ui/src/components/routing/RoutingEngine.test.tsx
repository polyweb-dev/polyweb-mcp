import { afterEach, describe, expect, it, vi } from "vitest"
import { act, fireEvent, render, screen, within, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { useFreeSearch } from "@/context/useFreeSearch"
import { RoutingEngine } from "./RoutingEngine"

function RoutingPresetProbe() {
  const { routingPreset } = useFreeSearch()
  return <output data-testid="routing-preset">{routingPreset}</output>
}

function DisableAllProvidersControl() {
  const { providers, toggleProvider } = useFreeSearch()
  return (
    <button
      type="button"
      data-testid="disable-all-providers"
      onClick={() => providers.forEach((provider) => toggleProvider(provider.id, false))}
    >
      Disable all providers
    </button>
  )
}

const renderRouting = (withProbe = false, withDisableControl = false) =>
  render(
    <FreeSearchProvider>
      <RoutingEngine />
      {withProbe && <RoutingPresetProbe />}
      {withDisableControl && <DisableAllProvidersControl />}
    </FreeSearchProvider>
  )

function rowContaining(label: string): HTMLElement {
  const cell = screen.getByText(label, { exact: true })
  return cell.parentElement ?? cell
}

describe("RoutingEngine", () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it("renders the four routing sub-tabs", () => {
    renderRouting()

    expect(screen.getByRole("heading", { name: /^Routing$/ })).toBeInTheDocument()
    expect(screen.getAllByRole("tab")).toHaveLength(4)
    for (const label of ["Strategy", "Simulator", "Ranks", "Resilience"]) {
      expect(screen.getByRole("tab", { name: new RegExp(`^${label}$`) })).toBeInTheDocument()
    }
  })

  it("renders each strategy card with its contract badge and description", () => {
    renderRouting()

    const cards = [
      ["Strict priority", "Manual ordering", "Routes to P1 provider first, cascades down user-defined ranks."],
      ["Cost optimized", "Zero-cost bias", "Prefers keyless tiers and free allotments before paid credits."],
      ["Latency optimized", "Fastest response", "Routes to the provider with lowest p95 roundtrip."],
      ["Quality first", "Rich extraction", "Prefers neural search and deep LLM extractors."],
    ] as const

    for (const [label, badge, description] of cards) {
      expect(screen.getByRole("button", { name: new RegExp(`^${label}`) })).toBeInTheDocument()
      expect(screen.getByText(badge, { exact: true })).toBeInTheDocument()
      expect(screen.getByText(description, { exact: true })).toBeInTheDocument()
    }
  })

  it("updates the routing preset when a strategy card is selected", async () => {
    const user = userEvent.setup()
    renderRouting(true)

    await user.click(screen.getByRole("button", { name: /^Latency optimized/ }))

    expect(screen.getByTestId("routing-preset")).toHaveTextContent("latency_optimized")
  })

  it("submits the simulator and renders ingress, primary, and fallback stages", async () => {
    const user = userEvent.setup()
    renderRouting()

    await user.click(screen.getByRole("tab", { name: /^Simulator$/ }))
    const input = screen.getByPlaceholderText("Type simulated query...", { exact: true })
    await user.type(input, "distributed systems benchmarks")
    await user.click(screen.getByRole("button", { name: /^Simulate route$/ }))

    await waitFor(() => {
      expect(screen.getByText("Client Ingress", { exact: true })).toBeVisible()
      expect(screen.getByText("Brave Search", { exact: true })).toBeVisible()
      expect(screen.getByText(/Failover cascade/i)).toBeVisible()
    })
  })

  it("snapshots the submitted operation while a simulation is pending", async () => {
    const user = userEvent.setup()
    renderRouting()

    await user.click(screen.getByRole("tab", { name: /^Simulator$/ }))
    await user.type(
      screen.getByPlaceholderText("Type simulated query...", { exact: true }),
      "search-only submission"
    )

    act(() => {
      fireEvent.click(screen.getByRole("button", { name: /^Simulate route$/ }))
    })

    const simulatorOperationGroup = within(
      screen.getByRole("group", { name: "Simulator operation" })
    )
    const fetchOpButton = simulatorOperationGroup.getByRole("button", {
      name: /^Fetch$/,
    })
    const searchOpButton = simulatorOperationGroup.getByRole("button", {
      name: /^Search$/,
    })
    expect(fetchOpButton).toBeDisabled()
    expect(searchOpButton).toBeDisabled()

    await waitFor(() => {
      expect(screen.getByText(/Incoming search/i)).toBeVisible()
      expect(screen.queryByText(/Incoming fetch/i)).not.toBeInTheDocument()
    })
  })

  it("renders an explicit empty state when no providers are eligible", async () => {
    const user = userEvent.setup()
    renderRouting(false, true)

    await user.click(screen.getByRole("tab", { name: /^Simulator$/ }))
    await user.click(screen.getByRole("button", { name: /^Disable all providers$/ }))

    expect(screen.getByText(/no eligible providers/i)).toBeInTheDocument()
    expect(screen.queryByText("Client Ingress", { exact: true })).not.toBeInTheDocument()
  })

  it("filters the ranks table by operation", async () => {
    const user = userEvent.setup()
    renderRouting()
    await user.click(screen.getByRole("tab", { name: /^Ranks$/ }))

    const table = screen.getByRole("table")
    expect(within(table).getAllByRole("row")).toHaveLength(7)

    await user.click(screen.getByRole("button", { name: /^Fetch$/ }))
    expect(within(table).getAllByRole("row")).toHaveLength(5)

    await user.click(screen.getByRole("button", { name: /^Search$/ }))
    expect(within(table).getAllByRole("row")).toHaveLength(7)
    const filter = screen.getByRole("textbox")
    await user.clear(filter)
    await user.type(filter, "Keenable")
    expect(within(table).getAllByRole("row")).toHaveLength(2)
  })

  it("preserves true rank and role when provider ranks are filtered", async () => {
    const user = userEvent.setup()
    renderRouting()
    await user.click(screen.getByRole("tab", { name: /^Ranks$/ }))

    const table = screen.getByRole("table")
    const primaryRow = within(table).getByRole("row", {
      name: /#1.*Brave Search.*Primary/,
    })
    const keenableRow = within(table).getByRole("row", {
      name: /#2.*Keenable.*Fallback/,
    })
    expect(primaryRow).toBeInTheDocument()
    expect(keenableRow).toBeInTheDocument()

    const filter = screen.getByRole("textbox")
    await user.clear(filter)
    await user.type(filter, "Keenable")

    const filteredKeenableRow = within(table).getByRole("row", {
      name: /#2.*Keenable.*Fallback/,
    })
    expect(filteredKeenableRow).toBeInTheDocument()
    expect(within(table).queryByRole("row", { name: /#1.*Keenable.*Primary/ })).not.toBeInTheDocument()
  })

  it("renders resilience depth, timeout budget, and circuit bypass state", async () => {
    const user = userEvent.setup()
    renderRouting()
    await user.click(screen.getByRole("tab", { name: /^Resilience$/ }))

    expect(screen.getByText("Cascade depth", { exact: true })).toBeInTheDocument()
    expect(within(rowContaining("Hop timeout budget")).getByText("3,000 ms", { exact: true })).toBeInTheDocument()
    expect(
      within(rowContaining("Circuit breaker auto-bypass")).getByText("Enabled", { exact: true })
    ).toBeInTheDocument()
  })
})
