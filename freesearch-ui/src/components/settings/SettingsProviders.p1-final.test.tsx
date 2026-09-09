import React from "react"
import { readFileSync } from "node:fs"
import path from "node:path"
import { describe, expect, it, afterEach, vi, beforeEach } from "vitest"
import { render, screen, within, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, useLocation } from "react-router"
import App from "@/App"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { SettingsView } from "./SettingsView"
import { installFetchStub, ok, err, deferred, type FetchStub } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
} from "@/test/backendFixtures"

/**
 * P1-FINAL Providers-into-Settings merge — BDD Acceptance (RED phase).
 *
 * User bullet (verbatim, feedback.md L56): "move Providers page into Settings
 * Providers tab as ONE table with all details + icon-opened test modal;
 * remove page entirely."
 * SEE images: .agents/FEEDBACK/UI/image-23.png (FLEET page: stat cards +
 * All/Search/Fetch/Keyless filter + Provider|Endpoint|Capabilities|Health|
 * p95|Quota|Actions table) + .agents/FEEDBACK/UI/image-24.png (REGISTRY tab:
 * Provider|Global|Search|Fetch|Test rows).
 *
 * Orchestrator rulings (confirmed plan): redirect /providers -> /settings;
 * DROP stat cards + fleet filter.
 *
 * Plan under test (freesearch-ui/ ONLY):
 *   SettingsProviders table expands to
 *     Provider|Endpoint|Global|Search|Fetch|Health|p95|Quota|Breaker|Test
 *   (registry controls preserved + fleet telemetry; min-w-1280 scroll);
 *   ProviderTestModal (Modal/Dialog wrapper, endpoint/caps/health/p95/quota/
 *   last-result, Test button = existing handleTest, icon opens / never fetches,
 *   Esc/scrim close); DELETE ProviderMatrix.tsx; App removes the providers
 *   route + adds /providers -> /settings redirect; Sidebar drops providers
 *   TabId/navItems/TAB_PATHS.
 *
 * AC mapping:
 *   P1F-1  ONE merged table: exact 10 headers in order, 7 rows x 10 cells,
 *          single ui/table.
 *   P1F-2  registry controls preserved: 7 global Switches (PATCH + pending),
 *          Search/Fetch segments (local-only), P1..P7 ranks + arrow boundaries.
 *   P1F-3  fleet telemetry per row: stripped Endpoint, Health dot+label, p95
 *          (exact ms, null -> "—"), Quota used/limit, Breaker Trip/Reset with
 *          Trip local-only (ZERO fetch) + Reset POST .../circuit-breaker/reset.
 *   P1F-4  ProviderTestModal: Modal/Dialog wrapper; icon button per row opens
 *          it with endpoint/caps/health/p95/quota/last-result; opening issues
 *          ZERO fetch; modal Test button runs existing handleTest (Testing...
 *          + exactly one POST .../test); Esc closes; overlay/scrim closes.
 *   P1F-5  DROP stat cards + fleet filter: no Total fleet / Health status /
 *          Zero-key / Fleet avg latency cards, no All/Search/Fetch/Keyless
 *          provider filter group in Settings. (Keep-guard: GREEN in Red.)
 *   P1F-6  page retired in source: App has no ProviderMatrix route, has the
 *          /providers -> /settings Navigate redirect; Sidebar has no
 *          "providers" TabId and no "/providers" target; SettingsProviders
 *          carries the fleet merge (Endpoint/Breaker/modal markers).
 *   P1F-7  1280 scroll: Table min-w-[1280px] inside the overflow-x-auto
 *          scroller; header/body cells nowrap.
 *   P1F-8  redirect behavior: MemoryRouter at /providers lands on /settings
 *          rendering the merged Settings registry; no Providers view remains.
 *
 * RED expectation (current baseline: 5-col registry, standalone /providers
 * ProviderMatrix page, text Test buttons, min-w-[880px]):
 *   P1F-1, P1F-3, P1F-4, P1F-6, P1F-7, P1F-8 FAIL cleanly. P1F-2 + P1F-5 PASS
 *   (preserved registry contracts + already-absent fleet chrome in Settings).
 */

const testDir = import.meta.dirname
const settingsSource =
  readFileSync(path.resolve(testDir, "./SettingsProviders.tsx"), "utf8") +
  "\n" +
  readFileSync(path.resolve(testDir, "./providers/ProviderRegistryRow.tsx"), "utf8") +
  "\n" +
  readFileSync(path.resolve(testDir, "./providers/OperationControl.tsx"), "utf8")
const appSource =
  readFileSync(path.resolve(testDir, "../../App.tsx"), "utf8") +
  "\n" +
  readFileSync(
    path.resolve(testDir, "../layout/DashboardContent.tsx"),
    "utf8"
  )
const sidebarSource = readFileSync(
  path.resolve(testDir, "../layout/Sidebar.tsx"),
  "utf8"
)

const SEED_PROVIDER_NAMES = [
  "Brave Search",
  "Keenable",
  "Tavily",
  "Exa",
  "Firecrawl",
  "You.com",
  "Parallel",
] as const

const EXPECTED_MERGED_HEADERS = [
  "Provider",
  "Endpoint",
  "Health",
  "Quota",
  "p95",
  "Test",
  "Search",
  "Fetch",
  "Global",
] as const

let testGate: Promise<Response> | null = null

function renderSettings(): FetchStub {
  testGate = null
  const stub = installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    if (req.method === "PATCH" && req.url.startsWith("/api/v1/providers/")) {
      const backendId = req.url.split("/").at(-1) ?? "unknown"
      const wire = allProvidersFixture().find((p) => p.provider_id === backendId)
      return ok({ ...(wire ?? allProvidersFixture()[0]), ...((req.body as object) ?? {}) })
    }
    if (req.method === "POST" && req.url.endsWith("/test")) {
      if (testGate) return testGate
      return ok({
        provider: "brave",
        ok: true,
        status: "healthy",
        latency_ms: 142,
        checked_at: "2026-09-06T10:04:00Z",
        detail: null,
      })
    }
    if (req.method === "POST" && req.url.endsWith("/circuit-breaker/reset")) {
      return ok({ provider: "x", state: "closed", updated_at: "2026-09-06T10:06:00Z" })
    }
    return err(404, { detail: "unhandled test route" })
  })
  render(
    <FreeSearchProvider>
      <SettingsView />
    </FreeSearchProvider>
  )
  return stub
}

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="test-location">{location.pathname}</div>
}

function renderAppAt(route: string): FetchStub {
  const stub = installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    return err(404, { detail: "unhandled test route" })
  })
  render(
    <MemoryRouter initialEntries={[route]}>
      <App />
      <LocationProbe />
    </MemoryRouter>
  )
  return stub
}

async function waitForProviders() {
  await waitFor(() => {
    expect(screen.getByText("Brave Search", { exact: true })).toBeInTheDocument()
  })
}

function mergedTable(): HTMLElement {
  return screen.getByRole("table")
}

function headerNames(): string[] {
  return Array.from(mergedTable().querySelectorAll("thead th")).map(
    (th) => th.textContent?.trim() ?? ""
  )
}

function findProviderRowTr(provider: string): HTMLTableRowElement {
  const nameEl = screen.getByText(provider, { exact: true })
  const tr = nameEl.closest("tr")
  if (!tr) {
    throw new Error(
      `Merged provider row <tr> not found for ${provider} — P1-FINAL table merge missing`
    )
  }
  return tr as HTMLTableRowElement
}

function cellFor(provider: string, header: string): HTMLElement {
  const row = findProviderRowTr(provider)
  const idx = headerNames().indexOf(header)
  if (idx < 0) throw new Error(`Merged table header not found: ${header} (got [${headerNames()}])`)
  const cell = row.children[idx] as HTMLElement | undefined
  if (!cell) throw new Error(`Cell ${header} (index ${idx}) missing in row ${provider}`)
  return cell
}

/** Icon button that opens the connection-test modal for a provider row. */
function testIconFor(provider: string): HTMLElement {
  const testCell = cellFor(provider, "Test")
  const btn = within(testCell).getByRole("button", { name: new RegExp(`${provider}.*test`, "i") })
  return btn
}

function openTestModalFor(provider: string): HTMLElement {
  const dialog = screen.queryByRole("dialog")
  if (dialog) throw new Error(`Expected no dialog before opening ${provider} test modal`)
  return dialog as unknown as HTMLElement
}

beforeEach(() => {
  window.localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

// ---------------------------------------------------------------------------
// P1F-1: ONE merged table with the exact 10 headers
// ---------------------------------------------------------------------------

describe("P1F-1: Settings registry is ONE merged table with 9 columns", () => {
  it("exposes the exact merged headers in order", async () => {
    renderSettings()
    await waitForProviders()
    expect(headerNames()).toEqual([...EXPECTED_MERGED_HEADERS])
  })

  it("renders a single table with 7 body rows", async () => {
    renderSettings()
    await waitForProviders()
    expect(screen.getAllByRole("table")).toHaveLength(1)
    expect(mergedTable().querySelectorAll("tbody tr")).toHaveLength(7)
    for (const name of SEED_PROVIDER_NAMES) {
      expect(findProviderRowTr(name)).toBeInTheDocument()
    }
  })

  it("gives every body row exactly 9 cells (merged columns never collapse)", async () => {
    renderSettings()
    await waitForProviders()
    const rows = Array.from(mergedTable().querySelectorAll("tbody tr"))
    expect(rows).toHaveLength(7)
    for (const row of rows) {
      expect(row.children).toHaveLength(EXPECTED_MERGED_HEADERS.length)
    }
  })

  it("reuses ui/table primitives for the merged table", () => {
    expect(settingsSource).toContain('from "@/components/ui/table"')
    for (const symbol of ["Table", "TableHeader", "TableBody", "TableRow", "TableHead", "TableCell"]) {
      expect(settingsSource, `SettingsProviders must reuse ${symbol}`).toContain(symbol)
    }
  })
})

// ---------------------------------------------------------------------------
// P1F-2: registry controls preserved (keep-guard, GREEN in Red)
// ---------------------------------------------------------------------------

describe("P1F-2: registry controls preserved in the merged table", () => {
  it("keeps 7 global Switches with provider-qualified labels", async () => {
    renderSettings()
    await waitForProviders()
    // 10-col header must exist AND the 7 switches must sit in Global cells.
    expect(headerNames()).toEqual([...EXPECTED_MERGED_HEADERS])
    for (const name of SEED_PROVIDER_NAMES) {
      const cell = cellFor(name, "Global")
      expect(
        within(cell).getByRole("switch", { name: `${name} global routing` })
      ).toBeInTheDocument()
    }
  })

  it("keeps Search/Fetch controls local-only with switch toggles", async () => {
    const user = userEvent.setup()
    const stub = renderSettings()
    await waitForProviders()
    const searchCell = cellFor("Brave Search", "Search")
    const searchSwitch = within(searchCell).getByRole("switch", { name: "Brave Search search routing" })
    expect(searchSwitch).toHaveAttribute("aria-checked", "true")
    await user.click(searchSwitch)
    expect(searchSwitch).toHaveAttribute("aria-checked", "false")
    expect(stub.requests.filter((r) => r.method === "PATCH")).toHaveLength(0)
  })

  it("shows priorities P1..P7 with bounded up/down controls per row", async () => {
    renderSettings()
    await waitForProviders()
    for (let rank = 1; rank <= 7; rank += 1) {
      expect(screen.getByText(`P${rank}`, { exact: true })).toBeInTheDocument()
    }
    expect(screen.queryByText("P100", { exact: true })).toBeNull()
    expect(
      screen.getByRole("button", { name: "Move Brave Search priority up" })
    ).toBeDisabled()
    expect(
      screen.getByRole("button", { name: "Move Parallel priority down" })
    ).toBeDisabled()
  })
})

// ---------------------------------------------------------------------------
// P1F-3: fleet telemetry per row (RED)
// ---------------------------------------------------------------------------

describe("P1F-3: fleet telemetry rides in the merged row", () => {
  it("shows the stripped upstream endpoint per row (protocol removed)", async () => {
    renderSettings()
    await waitForProviders()
    const braveEndpoint = cellFor("Brave Search", "Endpoint")
    expect(braveEndpoint.textContent).toContain("api.search.brave.com/res/v1/web/search")
    expect(braveEndpoint.textContent).not.toMatch(/https?:\/\//)
    const tavilyEndpoint = cellFor("Tavily", "Endpoint")
    expect(tavilyEndpoint.textContent).toContain("api.tavily.com")
  })

  it("shows a health dot + label per row", async () => {
    renderSettings()
    await waitForProviders()
    for (const name of SEED_PROVIDER_NAMES) {
      const health = cellFor(name, "Health")
      expect(health.textContent?.trim().length).toBeGreaterThan(0)
      expect(health.textContent).toMatch(/healthy|degraded|offline|unavailable|unknown|open/i)
    }
    expect(cellFor("Brave Search", "Health").textContent).toMatch(/healthy/i)
  })

  it("shows exact p95 latency per row (null renders '—')", async () => {
    renderSettings()
    await waitForProviders()
    // Fixture latency is 100 + rank*10: Brave (rank 1) reads exactly 110ms.
    expect(cellFor("Brave Search", "p95").textContent).toContain("110ms")
    for (const name of SEED_PROVIDER_NAMES) {
      expect(cellFor(name, "p95").textContent).toMatch(/\d+ms|—/)
      expect(cellFor(name, "p95").textContent).not.toMatch(/null|NaN/)
    }
  })

  it("shows quota used/limit per row without NaN", async () => {
    renderSettings()
    await waitForProviders()
    for (const name of SEED_PROVIDER_NAMES) {
      const quota = cellFor(name, "Quota")
      expect(quota.textContent?.trim().length).toBeGreaterThan(0)
      expect(quota.textContent).not.toMatch(/null|NaN/)
    }
    // Estimated quota (null/null) renders the "—/∞" form from the fleet page.
    expect(cellFor("Brave Search", "Quota").textContent).toContain("—/∞")
  })

  it("does not expose a Breaker column or Trip/Reset buttons", async () => {
    renderSettings()
    await waitForProviders()
    expect(screen.queryByText("Breaker")).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Trip" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Reset" })).not.toBeInTheDocument()
  })

  it("aligns p95 and quota fields with column header (left-aligned)", async () => {
    renderSettings()
    await waitForProviders()
    const p95 = cellFor("Brave Search", "p95")
    const quota = cellFor("Brave Search", "Quota")
    expect(p95.className).not.toContain("text-right")
    expect(quota.className).not.toContain("text-right")
  })
})

// ---------------------------------------------------------------------------
// P1F-4: icon-opened ProviderTestModal (RED)
// ---------------------------------------------------------------------------

describe("P1F-4: icon opens the ProviderTestModal (never fetches on open)", () => {
  it("declares the ProviderTestModal on a Modal/Dialog wrapper in source", () => {
    expect(settingsSource).toContain("ProviderTestModal")
    expect(
      settingsSource.includes("@/components/common/Modal") ||
        settingsSource.includes("@/components/ui/dialog") ||
        settingsSource.includes("from \"@/components/ui/dialog\"")
    ).toBe(true)
  })

  it("exposes one icon test button per row in the Test column", async () => {
    renderSettings()
    await waitForProviders()
    expect(headerNames()).toContain("Test")
    for (const name of SEED_PROVIDER_NAMES) {
      expect(testIconFor(name)).toBeInTheDocument()
    }
  })

  it("opening the modal issues ZERO fetch and shows endpoint/caps/health/p95/quota", async () => {
    const user = userEvent.setup()
    const stub = renderSettings()
    await waitForProviders()
    openTestModalFor("Brave Search")
    const callsBefore = stub.requests.length
    await user.click(testIconFor("Brave Search"))
    const dialog = await screen.findByRole("dialog")
    expect(stub.requests.length).toBe(callsBefore)
    expect(stub.requestsTo("/api/v1/providers/brave/test")).toHaveLength(0)
    expect(dialog.textContent).toContain("Brave Search")
    expect(dialog.textContent).toContain("api.search.brave.com")
    expect(dialog.textContent).toMatch(/healthy|degraded|offline|unknown/i)
    expect(dialog.textContent).toMatch(/\d+ms|—/)
    expect(dialog.textContent).toContain("—/∞")
  })

  it("modal Test button runs the existing handleTest: Testing... + exactly one POST .../test", async () => {
    const user = userEvent.setup()
    const gate = deferred<Response>()
    const stub = renderSettings()
    await waitForProviders()
    testGate = gate.promise
    await user.click(testIconFor("Brave Search"))
    const dialog = await screen.findByRole("dialog")
    const modalTest = within(dialog).getByRole("button", { name: /test/i })
    await user.click(modalTest)
    await waitFor(() => {
      expect(within(screen.getByRole("dialog")).getByRole("button", { name: /testing/i })).toBeInTheDocument()
    })
    gate.resolve(
      ok({
        provider: "brave",
        ok: true,
        status: "healthy",
        latency_ms: 142,
        checked_at: "2026-09-06T10:04:00Z",
        detail: null,
      })
    )
    await waitFor(() => {
      const tests = stub.requestsTo("/api/v1/providers/brave/test")
      expect(tests).toHaveLength(1)
      expect(tests[0].method).toBe("POST")
    })
    // Last result lands in the modal (status + latency of the probe).
    await waitFor(() => {
      expect(screen.getByRole("dialog").textContent).toMatch(/142ms|healthy/)
    })
  })

  it("Escape closes the test modal", async () => {
    const user = userEvent.setup()
    renderSettings()
    await waitForProviders()
    await user.click(testIconFor("Tavily"))
    await screen.findByRole("dialog")
    await user.keyboard("{Escape}")
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    })
  })

  it("overlay/scrim click closes the test modal", async () => {
    const user = userEvent.setup()
    renderSettings()
    await waitForProviders()
    await user.click(testIconFor("Tavily"))
    await screen.findByRole("dialog")
    const overlay = document.querySelector('[data-slot="dialog-overlay"]')
    expect(overlay, "Modal/Dialog must render a clickable overlay scrim").not.toBeNull()
    await user.click(overlay as HTMLElement)
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// P1F-5: stat cards + fleet filter dropped (keep-guard, GREEN in Red)
// ---------------------------------------------------------------------------

describe("P1F-5: fleet stat cards + capability filter are gone from Settings", () => {
  it("renders no fleet stat cards", async () => {
    renderSettings()
    await waitForProviders()
    for (const card of ["Total fleet", "Health status", "Zero-key tiers", "Fleet avg latency"]) {
      expect(screen.queryByText(card, { exact: true })).not.toBeInTheDocument()
    }
    expect(settingsSource).not.toMatch(/Total fleet/)
    expect(settingsSource).not.toMatch(/Fleet avg latency/)
  })

  it("renders no All/Search/Fetch/Keyless provider filter group", async () => {
    renderSettings()
    await waitForProviders()
    const groups = screen.queryAllByRole("group")
    const filters = groups.filter(
      (g) =>
        within(g).queryByRole("button", { name: /^all$/i }) &&
        within(g).queryByRole("button", { name: /^keyless$/i })
    )
    expect(filters).toHaveLength(0)
    expect(settingsSource).not.toMatch(/Provider filter/)
  })
})

// ---------------------------------------------------------------------------
// P1F-6: standalone Providers page retired (source contract, RED)
// ---------------------------------------------------------------------------

describe("P1F-6: Providers page retired — redirect + no providers nav", () => {
  it("App drops the ProviderMatrix route and redirects /providers -> /settings", () => {
    expect(appSource).not.toMatch(/ProviderMatrix/)
    expect(appSource).toContain('path="/providers"')
    const idx = appSource.indexOf('path="/providers"')
    const window_ = appSource.slice(idx, idx + 300)
    expect(window_, "/providers must Navigate to /settings").toMatch(/Navigate/)
    expect(window_, "/providers must Navigate to /settings").toContain("/settings")
  })

  it("Sidebar drops the providers TabId, nav item, and route target", () => {
    expect(sidebarSource).not.toContain('"providers"')
    expect(sidebarSource).not.toContain('"/providers"')
  })

  it("Sidebar renders exactly five workspace links (no Providers)", async () => {
    renderAppAt("/settings")
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Settings" })).toBeInTheDocument()
    })
    const nav = screen.getByRole("navigation", { name: "Primary" })
    expect(within(nav).getAllByRole("link")).toHaveLength(5)
    expect(within(nav).queryByRole("link", { name: "Providers", exact: true })).not.toBeInTheDocument()
    for (const label of ["Playground", "Routing", "Usage", "Activity", "Settings"]) {
      expect(within(nav).getByRole("link", { name: label, exact: true })).toBeInTheDocument()
    }
  })

  it("SettingsProviders carries the fleet merge markers", () => {
    for (const marker of ["Endpoint", "Health", "Quota", "p95", "ProviderTestModal"]) {
      expect(settingsSource, `merged table must carry ${marker}`).toContain(marker)
    }
  })
})

// ---------------------------------------------------------------------------
// P1F-7: min-w-1280 horizontal scroll (RED)
// ---------------------------------------------------------------------------

describe("P1F-7: merged table scrolls horizontally from 1280px", () => {
  it("Table carries min-w-[1280px] inside the overflow-x-auto scroller", async () => {
    renderSettings()
    await waitForProviders()
    const table = mergedTable()
    expect(table.className).toMatch(/min-w-\[1280px\]/)
    const container = table.closest('[data-slot="table-container"]') as HTMLElement | null
    expect(container, "ui/table scroller must wrap the merged table").not.toBeNull()
    expect(container!.className).toMatch(/overflow-x-auto/)
  })

  it("merged header + body cells keep nowrap (no wrapping)", async () => {
    renderSettings()
    await waitForProviders()
    const cells = Array.from(mergedTable().querySelectorAll("th, td")) as HTMLElement[]
    expect(cells.length).toBe(EXPECTED_MERGED_HEADERS.length + 7 * EXPECTED_MERGED_HEADERS.length)
    for (const cell of cells) {
      expect(cell.className).toMatch(/whitespace-nowrap/)
    }
  })
})

// ---------------------------------------------------------------------------
// P1F-8: /providers lands on the merged Settings registry (RED)
// ---------------------------------------------------------------------------

describe("P1F-8: legacy /providers URL renders the merged Settings registry", () => {
  it("navigating to /providers redirects to /settings", async () => {
    renderAppAt("/providers")
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Settings" })).toBeInTheDocument()
    })
    expect(screen.getByTestId("test-location").textContent).toBe("/settings")
  })

  it("the redirect target shows the merged registry (9 headers, no Providers view)", async () => {
    renderAppAt("/providers")
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Settings" })).toBeInTheDocument()
    })
    expect(headerNames()).toEqual([...EXPECTED_MERGED_HEADERS])
    expect(screen.queryByRole("heading", { name: "Providers" })).not.toBeInTheDocument()
  })
})
