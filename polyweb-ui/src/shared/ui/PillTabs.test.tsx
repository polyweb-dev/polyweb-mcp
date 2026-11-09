import React from "react"
import { describe, it, expect, afterEach, vi } from "vitest"
import { render, screen, waitFor, within, cleanup } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, useLocation } from "react-router"
import { PolywebProvider } from "@/context/PolywebContext"
import { Header } from "@/components/layout/Header"
import { PlaygroundHarness } from "@/test/renderPlayground"
import { answerProjectProviders } from "@/test/projectPlayground"
import { SettingsView } from "@/features/system-providers/ui/SettingsView"
import { tabsListVariants } from "@/shared/ui/tabs"
import { PillTabs } from "@/shared/ui/PillTabs"
import { PillTabsList } from "@/shared/ui/PillTabsList"
import { PillTabsPanel } from "@/shared/ui/PillTabsPanel"
import { AuthContext } from "@/domains/auth/state/context"
import { authenticatedContextValue } from "@/test/renderAuthenticated"
import { installFetchStub, ok, err } from "@/test/fetchMock"
import { ADMIN_ACCOUNT_ID, adminAccountFixture } from "@/test/authFixtures"
import { ProjectsContext } from "@/domains/projects/state/context"
import {
  SETTINGS_READER_PERMISSIONS,
  SYSTEM_ADMIN_PERMISSIONS,
  projectsContextFixture,
  systemAccessFixture,
} from "@/test/accessFixtures"
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
  return render(<PolywebProvider accountId={ADMIN_ACCOUNT_ID} canReadControls canEditControls>{ui}</PolywebProvider>)
}

/** Render the system provider catalog with a settings-reader descriptor. */
function renderSettingsView() {
  return renderWithBackend(
    <MemoryRouter initialEntries={["/system/providers"]}>
      <ProjectsContext.Provider
        value={projectsContextFixture({ systemAccess: systemAccessFixture(SETTINGS_READER_PERMISSIONS) })}
      >
        <SettingsView />
      </ProjectsContext.Provider>
    </MemoryRouter>
  )
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
        screen.getByPlaceholderText(/Search the web/i)
      ).toBeInTheDocument()
    })
  }

  it("exposes Search + Fetch as pill tabs", async () => {
    await ready()
    expectPillList(["Search", "Fetch"])
  })

  it("docks the pill tabs as the first control of the composer input row", async () => {
    await ready()
    const pill = expectPillList(["Search", "Fetch"])
    const composer = screen.getByTestId("search-composer")
    const footer = screen.getByTestId("search-composer-footer")
    const input = screen.getByPlaceholderText(/Search the web/i)
    expect(composer.contains(pill)).toBe(true)
    expect(footer.contains(pill)).toBe(false)
    // Mode first, then the query: the pill precedes the input in DOM order.
    expect(pill.compareDocumentPosition(input) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0)
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

describe("C2-REWORK AC-C2R-1/2/3: SettingsView pill switcher", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  /** Even a key manager sees only the provider catalog on this page. */
  function renderWithKeyManagement() {
    return renderWithBackend(
      <MemoryRouter initialEntries={["/system/providers"]}>
        <ProjectsContext.Provider
          value={projectsContextFixture({
            systemAccess: systemAccessFixture([...SETTINGS_READER_PERMISSIONS, "system.credentials.manage"]),
          })}
        >
          <SettingsView />
        </ProjectsContext.Provider>
      </MemoryRouter>
    )
  }

  async function ready() {
    renderWithKeyManagement()
    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 2, name: "Providers" })).toBeInTheDocument()
    })
  }

  it("exposes Providers and Keys as pill tabs, docked top-right (now a single catalog without tabs)", async () => {
    await ready()
    expect(screen.getByRole("heading", { name: "When a provider fails" })).toBeInTheDocument()
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument()
    expect(screen.queryByRole("tab")).not.toBeInTheDocument()
  })

  function renderTwoTabs() {
    return render(
      <PillTabs
        options={[{ value: "first", label: "First" }, { value: "second", label: "Second" }]}
        ariaLabel="Example views"
        idPrefix="example"
        defaultValue="first"
      >
        <PillTabsList />
        <PillTabsPanel value="first">First panel</PillTabsPanel>
        <PillTabsPanel value="second">Second panel</PillTabsPanel>
      </PillTabs>
    )
  }

  it("switching pill tabs swaps panels (Keys, then back to Providers) (two-tab fixture)", async () => {
    const user = userEvent.setup()
    renderTwoTabs()
    expectPillList(["First", "Second"])
    expect(screen.getByRole("tabpanel")).toHaveTextContent("First panel")
    await user.click(screen.getByRole("tab", { name: "Second" }))
    expect(screen.getByRole("tab", { name: "Second" })).toHaveAttribute("aria-selected", "true")
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Second panel")
    await user.click(screen.getByRole("tab", { name: "First" }))
    expect(screen.getByRole("tab", { name: "First" })).toHaveAttribute("aria-selected", "true")
    expect(screen.getByRole("tabpanel")).toHaveTextContent("First panel")
  })

  it("arrow keys move focus between pill tabs; Enter activates selection (two-tab fixture)", async () => {
    const user = userEvent.setup()
    renderTwoTabs()

    const firstTab = screen.getByRole("tab", { name: "First" })
    const secondTab = screen.getByRole("tab", { name: "Second" })
    await user.tab()
    expect(firstTab).toHaveFocus()

    await user.keyboard("{ArrowRight}")
    await waitFor(() => {
      expect(secondTab).toHaveFocus()
    })
    expect(firstTab).toHaveAttribute("aria-selected", "true")
    expect(secondTab).toHaveAttribute("aria-selected", "false")

    await user.keyboard("{Enter}")
    await waitFor(() => {
      expect(secondTab).toHaveAttribute("aria-selected", "true")
    })
    expect(firstTab).toHaveAttribute("aria-selected", "false")
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Second panel")
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
        screen.getByPlaceholderText(/Search the web/i)
      ).toBeInTheDocument()
    })
    cleanup()

    renderSettingsView()
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Providers" })).toBeInTheDocument()
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

  it("Header compatibility shim exposes seven router links and zero tab roles (now five links)", async () => {
    const user = userEvent.setup()

    function LocationProbe() {
      return <output data-testid="header-route">{useLocation().pathname}</output>
    }

    render(
      <MemoryRouter initialEntries={["/account"]}>
        <AuthContext.Provider value={authenticatedContextValue(adminAccountFixture())}>
          {/* U1: the navigation filters on the live system access, not a role. */}
          <ProjectsContext.Provider value={projectsContextFixture({
            systemAccess: systemAccessFixture([...SYSTEM_ADMIN_PERMISSIONS, "vault.manage"]),
          })}>
            <Header />
            <LocationProbe />
          </ProjectsContext.Provider>
        </AuthContext.Provider>
      </MemoryRouter>
    )

    // Global navigation exposes the catalog, quotas and account-scoped vault.
    const headerNav = screen.getByRole("navigation", { name: "Primary" })
    const links = within(headerNav).getAllByRole("link")
    expect(links.map((link) => link.getAttribute("aria-label"))).toEqual([
      "Providers", "Quotas", "Projects", "Keys and pools", "Account",
    ])
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/system/providers", "/system/quotas", "/projects", "/account/keys", "/account",
    ])
    expect(headerNav.querySelector('a[href="/providers"]')).toBeNull()
    expect(
      within(headerNav).queryByRole("link", { name: "System credentials", exact: true })
    ).not.toBeInTheDocument()
    expect(screen.queryByRole("tab")).not.toBeInTheDocument()
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument()
    expect(screen.queryByRole("tabpanel")).not.toBeInTheDocument()

    await user.click(screen.getByRole("link", { name: "Providers" }))
    expect(screen.getByTestId("header-route")).toHaveTextContent("/system/providers")
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
