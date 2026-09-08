import React from "react"
import { describe, it, expect, afterEach, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { Header } from "@/components/layout/Header"
import { RoutingEngine } from "@/components/routing/RoutingEngine"
import { SettingsView } from "@/components/settings/SettingsView"
import { SegmentedControl } from "./SegmentedControl"
import { installFetchStub, ok, err } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
} from "@/test/backendFixtures"

/**
 * C2-REWORK canonical contracts + scope guards.
 *
 * - PillTabs (ui/tabs `pill` variant, as used by SearchPlayground /
 *   RoutingEngine / SettingsView) is the GOLD STANDARD: these assertions pin
 *   the exact contract the migrated slots must adopt — provider-page pill
 *   look, always top-right in the page header. The prior Tabs(line) consensus
 *   is VOID.
 * - SegmentedControl stays the single filter contract (ProviderMatrix,
 *   Ranks/Simulator operation, Depth): role=group, exclusive aria-pressed.
 * - Header scope (AC-C2-5): the top nav stays plain buttons — never role=tab —
 *   and switching views must not touch the URL (no router is introduced;
 *   package.json was verified to contain no react-router/wouter dependency).
 */
function renderWithBackend(ui: React.ReactElement) {
  installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    return err(404, { detail: "unhandled test route" })
  })
  return render(<FreeSearchProvider>{ui}</FreeSearchProvider>)
}

describe("C2 gold: SegmentedControl filter contract", () => {
  it("renders a named group with exactly one aria-pressed=true", async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(
      <SegmentedControl
        options={["Search", "Fetch"]}
        value="Search"
        onChange={onChange}
        ariaLabel="Ranks operation"
      />
    )

    const group = screen.getByRole("group", { name: "Ranks operation" })
    expect(group).toBeInTheDocument()
    expect(
      within(group).getByRole("button", { name: "Search" })
    ).toHaveAttribute("aria-pressed", "true")
    expect(
      within(group).getByRole("button", { name: "Fetch" })
    ).toHaveAttribute("aria-pressed", "false")

    await user.click(within(group).getByRole("button", { name: "Fetch" }))
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange).toHaveBeenCalledWith("Fetch")
  })

  it("disables every segment while an operation is in flight", () => {
    render(
      <SegmentedControl
        options={["Search", "Fetch"]}
        value="Search"
        onChange={() => {}}
        ariaLabel="Simulator operation"
        disabled
      />
    )

    const group = screen.getByRole("group", { name: "Simulator operation" })
    for (const label of ["Search", "Fetch"]) {
      expect(
        within(group).getByRole("button", { name: label })
      ).toBeDisabled()
    }
  })
})

describe("C2-REWORK gold: RoutingEngine + SettingsView are canonical Tabs(pill)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("RoutingEngine exposes Strategy/Simulator/Ranks/Resilience as pill tabs", async () => {
    renderWithBackend(<RoutingEngine />)
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: "Routing" })
      ).toBeInTheDocument()
    })

    const pillList = document.querySelector(
      '[data-slot="tabs-list"][data-variant="pill"]'
    )
    expect(pillList).not.toBeNull()
    const tabs = within(pillList as HTMLElement).getAllByRole("tab")
    expect(tabs.map((t) => t.textContent)).toEqual([
      "Strategy",
      "Simulator",
      "Ranks",
      "Resilience",
    ])
    expect(
      screen.getByRole("tab", { name: "Strategy" })
    ).toHaveAttribute("aria-selected", "true")
  })

  it("RoutingEngine tab switch swaps panels (Simulator)", async () => {
    const user = userEvent.setup()
    renderWithBackend(<RoutingEngine />)
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "Simulator" })).toBeInTheDocument()
    })

    await user.click(screen.getByRole("tab", { name: "Simulator" }))

    expect(screen.getByRole("tab", { name: "Simulator" })).toHaveAttribute(
      "aria-selected",
      "true"
    )
    expect(
      screen.getByPlaceholderText("Type simulated query...", { exact: true })
    ).toBeInTheDocument()
  })

  it("SettingsView exposes Providers/Keys/Failover as pill tabs", async () => {
    renderWithBackend(<SettingsView />)
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: "Settings" })
      ).toBeInTheDocument()
    })

    const pillList = document.querySelector(
      '[data-slot="tabs-list"][data-variant="pill"]'
    )
    expect(pillList).not.toBeNull()
    const tabs = within(pillList as HTMLElement).getAllByRole("tab")
    expect(tabs.map((t) => t.textContent)).toEqual([
      "Providers",
      "Keys",
      "Failover",
    ])
    expect(screen.getByText("Provider registry")).toBeInTheDocument()
  })

  it("SettingsView tab switch swaps panels (Keys -> Key vault)", async () => {
    const user = userEvent.setup()
    renderWithBackend(<SettingsView />)
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "Keys" })).toBeInTheDocument()
    })

    await user.click(screen.getByRole("tab", { name: "Keys" }))

    expect(screen.getByRole("tab", { name: "Keys" })).toHaveAttribute(
      "aria-selected",
      "true"
    )
    expect(screen.getByText("Key vault")).toBeInTheDocument()
  })
})

describe("C2 AC-C2-5: Header nav scope — plain buttons, no router", () => {
  it("renders six navigation buttons and zero tab roles", async () => {
    const onSelectTab = vi.fn()
    const user = userEvent.setup()
    render(<Header activeTab="playground" onSelectTab={onSelectTab} />)

    for (const label of [
      "Playground",
      "Providers",
      "Routing",
      "Usage",
      "Activity",
      "Settings",
    ]) {
      expect(
        screen.getByRole("button", { name: label, exact: true })
      ).toBeInTheDocument()
    }
    expect(screen.queryByRole("tab")).not.toBeInTheDocument()
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument()
    expect(screen.queryByRole("tabpanel")).not.toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "Routing" }))
    expect(onSelectTab).toHaveBeenCalledTimes(1)
    expect(onSelectTab).toHaveBeenCalledWith("routing")
  })

  it("header navigation never changes the URL", async () => {
    const onSelectTab = vi.fn()
    const user = userEvent.setup()
    render(<Header activeTab="playground" onSelectTab={onSelectTab} />)
    const before = window.location.href

    await user.click(screen.getByRole("button", { name: "Providers" }))
    await user.click(screen.getByRole("button", { name: "Settings" }))

    expect(window.location.href).toBe(before)
    expect(window.location.pathname).toBe("/")
    expect(onSelectTab).toHaveBeenNthCalledWith(1, "providers")
    expect(onSelectTab).toHaveBeenNthCalledWith(2, "settings")
  })
})
