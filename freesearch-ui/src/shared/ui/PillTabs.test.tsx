import React from "react"
import { describe, it, expect, afterEach, vi } from "vitest"
import { render, screen, waitFor, within, cleanup } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, useLocation } from "react-router"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { Header } from "@/components/layout/Header"
import { PlaygroundHarness } from "@/test/renderPlayground"
import { answerProjectProviders } from "@/test/projectPlayground"
import { RoutingEngine } from "@/components/routing/RoutingEngine"
import { SettingsView } from "@/components/settings/SettingsView"
import { tabsListVariants } from "@/shared/ui/tabs"
import { AuthContext } from "@/domains/auth/state/context"
import { authenticatedContextValue } from "@/test/renderAuthenticated"
import { installFetchStub, ok, err } from "@/test/fetchMock"
import { ADMIN_ACCOUNT_ID, adminAccountFixture } from "@/test/authFixtures"
import { ProjectsContext } from "@/domains/projects/state/context"
import { projectsContextFixture } from "@/test/accessFixtures"
import { allProvidersFixture, routingConfigFixture, dashboardFixture, searchResponseFixture, fetchResponseFixture } from "@/test/backendFixtures"

describe("PillTabs.c2r.test.tsx", () => {

/**
 * C2-REWORK acceptance (RED): the provider-page pill
 * (All/Search/Fetch/Keyless) is the target look. Every view-switcher —
 * SearchPlayground (Search/Fetch), RoutingEngine (Strategy/Simulator/Ranks/
 * Resilience), SettingsView (Providers/Keys/Failover) — must be the reusable
 * `common/PillTabs` control (ui/tabs `pill` variant, tab semantics) docked
 * top-right in its page header. ProviderMatrix filter + Header are untouched.
 *
 * AC-C2R-1: pill look parity on all 3 pages (PillTabs reuse + pill variant).
 * AC-C2R-2: top-right placement (pill lives in the header-right row, LAST —
 *   no visible trailing siblings).
 * AC-C2R-3: tab semantics + panel swap + keyboard (tablist/tab/tabpanel,
 *   exclusive aria-selected, aria-controls/id linkage, manual activation).
 * AC-C2R-4: no filter/Header regression (SegmentedControl filters stay
 *   role=group; Header stays plain buttons; no router/URL change; no line
 *   variant remains in view-switcher slots).
 *
 * Final-review expectation: pill-last placement FAILS on Search/Routing
 * (trailing status siblings follow the pill) and PASSES on Settings;
 * the production placement fix rides separately with the Developer.
 */
function renderWithBackend(ui: React.ReactElement) {
  installFetchStub((req) => {
    const projectView = answerProjectProviders(req)
    if (projectView !== null) return projectView
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    if (req.url === "/search" && req.method === "POST") {
      return ok(searchResponseFixture())
    }
    if (req.url === "/fetch" && req.method === "POST") {
      return ok(fetchResponseFixture())
    }
    return err(404, { detail: "unhandled test route" })
  })
  return render(<FreeSearchProvider accountId={ADMIN_ACCOUNT_ID} canReadControls canEditControls>{ui}</FreeSearchProvider>)
}

/** Nearest spread header row (`justify-between`: title left, pill right). */
function headerRowFor(headingName: string): HTMLElement | null {
  const heading = screen.getByRole("heading", { name: headingName })
  return heading.closest('div[class*="justify-between"]') as HTMLElement | null
}

function expectPillList(labels: string[]): HTMLElement {
  const pillList = document.querySelector(
    '[data-slot="tabs-list"][data-variant="pill"]'
  )
  expect(pillList, "pill tablist [data-variant=pill] must exist").not.toBeNull()
  const tabs = within(pillList as HTMLElement).getAllByRole("tab")
  expect(tabs.map((t) => t.textContent)).toEqual(labels)
  return pillList as HTMLElement
}

function expectTopRight(headingName: string, pillList: HTMLElement) {
  const row = headerRowFor(headingName)
  expect(
    row,
    `${headingName} must have a justify-between header row (title left, pill right)`
  ).not.toBeNull()
  expect(
    row!.contains(pillList),
    "pill tablist must live inside the header row (header-right)"
  ).toBe(true)
  const heading = screen.getByRole("heading", { name: headingName })
  expect(
    (heading.compareDocumentPosition(pillList) &
      Node.DOCUMENT_POSITION_FOLLOWING) !==
      0,
    "pill must follow the title in DOM order (right side of the row)"
  ).toBe(true)
  // Pill is the LAST visible element in the header row: no non-hidden
  // trailing siblings allowed (status ribbons belong ahead of or below the
  // pill, never after it). aria-hidden separators/paint are ignored, as are
  // the pill's own tabs and its ancestor wrappers.
  const trailing = Array.from(row!.querySelectorAll("*")).filter((el) => {
    if (el === pillList || pillList.contains(el) || el.contains(pillList)) {
      return false
    }
    if ((el as HTMLElement).closest('[aria-hidden="true"]')) return false
    return (
      (pillList.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) !==
      0
    )
  })
  expect(
    trailing.map((el) => el.textContent?.trim() || el.tagName),
    "pill tablist must be the last visible element in the header row — reject trailing siblings"
  ).toEqual([])
  // Panels render below the header, never inside it.
  for (const panel of screen.getAllByRole("tabpanel")) {
    expect(row!.contains(panel), "tabpanel must not sit inside the header row").toBe(
      false
    )
  }
}

describe("C2-REWORK AC-C2R-1: pill variant + reusable PillTabs", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("ui/tabs exposes a bordered pill variant (provider-filter look, not the line wash)", () => {
    const asVariant = tabsListVariants as unknown as (args: {
      variant: string
    }) => string
    const pill = asVariant({ variant: "pill" })
    // Boxed pill container like the provider filter: visible border box…
    expect(pill, "pill variant must render a bordered box").toContain("border")
    // …rounded container…
    expect(pill, "pill variant must be rounded").toMatch(/rounded-(md|lg|full)/)
    // …and never the VOID transparent underline wash.
    expect(pill, "pill variant must not be the transparent line wash").not.toContain(
      "bg-transparent"
    )
  })
})

describe("C2-REWORK AC-C2R-1/2/3: SearchPlayground pill switcher", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  async function ready() {
    renderWithBackend(<PlaygroundHarness />)
    await waitFor(() => {
      expect(
        screen.getByPlaceholderText(/Search across all providers/i)
      ).toBeInTheDocument()
    })
  }

  it("exposes Search + Fetch as pill tabs", async () => {
    await ready()
    expectPillList(["Search", "Fetch"])
  })

  it("docks the pill tabs inside the composer island footer", async () => {
    await ready()
    const pill = expectPillList(["Search", "Fetch"])
    const footer = screen.getByTestId("search-composer-footer")
    expect(footer.contains(pill)).toBe(true)
  })

  it("keeps exclusive aria-selected with tab/panel linkage", async () => {
    await ready()
    expectPillList(["Search", "Fetch"])

    expect(screen.getByRole("tab", { name: "Search" })).toHaveAttribute(
      "aria-selected",
      "true"
    )
    expect(screen.getByRole("tab", { name: "Fetch" })).toHaveAttribute(
      "aria-selected",
      "false"
    )
    const searchTab = screen.getByRole("tab", { name: "Search" })
    const controls = searchTab.getAttribute("aria-controls")
    const tabId = searchTab.getAttribute("id")
    expect(controls?.trim().length).toBeGreaterThan(0)
    expect(tabId?.trim().length).toBeGreaterThan(0)
    const panels = screen.getAllByRole("tabpanel")
    expect(panels).toHaveLength(1)
    expect(panels[0]).toHaveAttribute("id", controls!)
    expect(panels[0]).toHaveAttribute("aria-labelledby", tabId!)
  })
})

describe("C2-REWORK AC-C2R-1/2/3: RoutingEngine pill switcher", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  async function ready() {
    renderWithBackend(<RoutingEngine />)
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Routing" })).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "Simulator" })).toBeInTheDocument()
    })
  }

  it("exposes the two routing views as pill tabs, docked top-right", async () => {
    await ready()
    const pillList = expectPillList([
      "Strategy",
      "Simulator",
    ])
    expectTopRight("Routing", pillList)
    expect(screen.getByRole("tab", { name: "Strategy" })).toHaveAttribute(
      "aria-selected",
      "true"
    )
  })

  it("switching pill tabs swaps panels (Simulator, then back to Strategy)", async () => {
    const user = userEvent.setup()
    await ready()

    await user.click(screen.getByRole("tab", { name: "Simulator" }))
    expect(screen.getByRole("tab", { name: "Simulator" })).toHaveAttribute(
      "aria-selected",
      "true"
    )
    expect(
      screen.getByPlaceholderText("Type simulated query...", { exact: true })
    ).toBeInTheDocument()

    await user.click(screen.getByRole("tab", { name: "Strategy" }))
    expect(screen.getByRole("tab", { name: "Strategy" })).toHaveAttribute(
      "aria-selected",
      "true"
    )
    expect(
      screen.getByRole("button", { name: /^Latency optimized/ })
    ).toBeInTheDocument()
    expect(
      screen.queryByPlaceholderText("Type simulated query...", { exact: true })
    ).not.toBeInTheDocument()
  })

  it("arrow keys move focus between pill tabs; Enter activates selection", async () => {
    const user = userEvent.setup()
    await ready()

    const strategyTab = screen.getByRole("tab", { name: "Strategy" })
    const simulatorTab = screen.getByRole("tab", { name: "Simulator" })
    strategyTab.focus()
    expect(strategyTab).toHaveFocus()

    // Manual activation: arrows move focus, not selection.
    await user.keyboard("{ArrowRight}")
    await waitFor(() => {
      expect(simulatorTab).toHaveFocus()
    })
    expect(strategyTab).toHaveAttribute("aria-selected", "true")
    expect(simulatorTab).toHaveAttribute("aria-selected", "false")

    await user.keyboard("{Enter}")
    await waitFor(() => {
      expect(simulatorTab).toHaveAttribute("aria-selected", "true")
    })
    expect(strategyTab).toHaveAttribute("aria-selected", "false")
  })
})

describe("C2-REWORK AC-C2R-1/2/3: SettingsView pill switcher", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  async function ready() {
    renderWithBackend(<SettingsView />)
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Settings" })).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "Failover" })).toBeInTheDocument()
    })
  }

  // U3: the Keys tab is gone (provider secrets live on credential
  // instances), so the switcher has exactly two views.
  it("exposes the two settings views as pill tabs, docked top-right", async () => {
    await ready()
    const pillList = expectPillList(["Providers", "Failover"])
    expectTopRight("Settings", pillList)
    expect(screen.getByText("Provider registry")).toBeInTheDocument()
  })

  it("switching pill tabs swaps panels (Failover, then back to Providers)", async () => {
    const user = userEvent.setup()
    await ready()

    await user.click(screen.getByRole("tab", { name: "Failover" }))
    expect(screen.getByRole("tab", { name: "Failover" })).toHaveAttribute(
      "aria-selected",
      "true"
    )
    expect(screen.getByText("Failover policy")).toBeInTheDocument()
    expect(screen.queryByText("Provider registry")).not.toBeInTheDocument()

    await user.click(screen.getByRole("tab", { name: "Providers" }))
    expect(screen.getByRole("tab", { name: "Providers" })).toHaveAttribute(
      "aria-selected",
      "true"
    )
    expect(screen.getByText("Provider registry")).toBeInTheDocument()
    expect(screen.queryByText("Failover policy")).not.toBeInTheDocument()
  })

  it("arrow keys move focus between pill tabs; Enter activates selection", async () => {
    const user = userEvent.setup()
    await ready()

    const providersTab = screen.getByRole("tab", { name: "Providers" })
    const failoverTab = screen.getByRole("tab", { name: "Failover" })
    providersTab.focus()
    expect(providersTab).toHaveFocus()

    await user.keyboard("{ArrowRight}")
    await waitFor(() => {
      expect(failoverTab).toHaveFocus()
    })
    expect(providersTab).toHaveAttribute("aria-selected", "true")
    expect(failoverTab).toHaveAttribute("aria-selected", "false")

    await user.keyboard("{Enter}")
    await waitFor(() => {
      expect(failoverTab).toHaveAttribute("aria-selected", "true")
    })
    expect(providersTab).toHaveAttribute("aria-selected", "false")
    expect(screen.getByText("Failover policy")).toBeInTheDocument()
  })
})

describe("C2-REWORK AC-C2R-4: no filter/Header regression", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("no line variant remains in any view-switcher slot", async () => {
    renderWithBackend(<PlaygroundHarness />)
    await waitFor(() => {
      expect(
        screen.getByPlaceholderText(/Search across all providers/i)
      ).toBeInTheDocument()
    })
    cleanup()

    renderWithBackend(<RoutingEngine />)
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Routing" })).toBeInTheDocument()
    })
    cleanup()

    renderWithBackend(<SettingsView />)
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Settings" })).toBeInTheDocument()
    })

    // Every page re-rendered above leaves its tablist mounted; none may be line.
    expect(
      document.querySelectorAll('[data-slot="tabs-list"][data-variant="line"]')
    ).toHaveLength(0)
  })

  // P1-FINAL (blessed inversion, NOT a regression): the fleet capability
  // filter (All/Search/Fetch/Keyless) is DROPPED with the Providers page
  // merge — its SegmentedControl group no longer exists anywhere, so the
  // filter-preservation case is RETIRED. Filter narrowing is covered by the
  // merged Settings registry suite (SettingsProviders.p1-final.test.tsx).

  it("Header compatibility shim exposes eight router links and zero tab roles", async () => {
    const user = userEvent.setup()

    function LocationProbe() {
      return <output data-testid="header-route">{useLocation().pathname}</output>
    }

    render(
      <MemoryRouter initialEntries={["/account"]}>
        <AuthContext.Provider value={authenticatedContextValue(adminAccountFixture())}>
          {/* U1: the navigation filters on the live system access, not a role. */}
          <ProjectsContext.Provider value={projectsContextFixture()}>
            <Header />
            <LocationProbe />
          </ProjectsContext.Provider>
        </AuthContext.Provider>
      </MemoryRouter>
    )

    // P1-FINAL: standalone Providers page retired — five workspace links.
    // R-UI: Account and Admin screens entered scope; U1 adds Projects, so the
    // system administrator sees eight. U2 moves Playground and Activity under
    // projects, so six global links remain. U3 adds System credentials and
    // Capacity and renames Settings to Provider settings: eight links.
    const headerNav = screen.getByRole("navigation", { name: "Primary" })
    expect(within(headerNav).getAllByRole("link")).toHaveLength(8)
    expect(
      within(headerNav).queryByRole("link", { name: "Providers", exact: true })
    ).not.toBeInTheDocument()
    for (const label of [
      "Routing",
      "Provider usage",
      "System credentials",
      "Capacity",
      "Provider settings",
      "Projects",
      "Account",
      "Admin",
    ]) {
      expect(screen.getByRole("link", { name: label, exact: true })).toBeInTheDocument()
    }
    expect(screen.queryByRole("tab")).not.toBeInTheDocument()
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument()
    expect(screen.queryByRole("tabpanel")).not.toBeInTheDocument()

    await user.click(screen.getByRole("link", { name: "Routing" }))
    expect(screen.getByTestId("header-route")).toHaveTextContent("/routing")
    await user.click(screen.getByRole("link", { name: "Provider settings" }))
    expect(screen.getByTestId("header-route")).toHaveTextContent("/settings")
  })
})
})

describe("PillTabs.module.c2r.test.tsx", () => {

/**
 * C2-REWORK AC-C2R-1 (RED): the plan requires a NEW reusable
 * `shared/ui/PillTabs.tsx` (provider-page pill look with tab semantics:
 * tablist/tab/tabpanel, aria-selected, linkage, keyboard) consumed by
 * SearchPlayground, RoutingEngine, and SettingsView.
 *
 * Red expectation: this file fails to resolve `@/shared/ui/PillTabs` (the
 * module does not exist yet), which is the clean non-vacuous proof. It goes
 * green once the Developer creates the module; per-page pill behavior is
 * pinned by `PillTabs.c2r.test.tsx`. (CLEANUP 1.1: the `common/PillTabs`
 * compat shell was removed; the canonical module lives in shared/ui.)
 */
describe("C2-REWORK AC-C2R-1: reusable PillTabs module exists", () => {
  it("shared/ui/PillTabs exposes a reusable view-switcher component", async () => {
    const mod = (await import("@/shared/ui/PillTabs").catch(() => null)) as null | {
      PillTabs?: unknown
      default?: unknown
    }
    expect(mod, "shared/ui/PillTabs module must exist").not.toBeNull()
    const PillTabs =
      (mod as { PillTabs?: unknown }).PillTabs ??
      (mod as { default?: unknown }).default
    expect(typeof PillTabs, "PillTabs must be a component").toBe("function")
  })
})
})
