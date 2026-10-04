import React from "react"
import { readFileSync, existsSync } from "node:fs"
import path from "node:path"
import { describe, expect, it, afterEach, vi, beforeEach } from "vitest"
import { render, screen, within, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, useLocation } from "react-router"
import App from "@/App"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { SettingsView } from "./SettingsView"
import { installFetchStub, ok, err, deferred, type FetchStub } from "@/test/fetchMock"
import { allProvidersFixture, routingConfigFixture, dashboardFixture } from "@/test/fixtures"
import { type WireProviderStatus } from "@/test/backendFixtures"

describe("SettingsProviders.p1-final.test.tsx", () => {

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
 *     Provider|Endpoint|Health|Test|Search|Fetch|Global
 *   (registry controls preserved + endpoint/health telemetry; min-w-960 scroll);
 *   ProviderTestModal (Modal/Dialog wrapper, endpoint/caps/health/p95/quota/
 *   last-result, Test button = existing handleTest, icon opens / never fetches,
 *   Esc/scrim close); DELETE ProviderMatrix.tsx; App removes the providers
 *   route + adds /providers -> /settings redirect; Sidebar drops providers
 *   TabId/navItems/TAB_PATHS.
 *
 * AC mapping:
 *   P1F-1  ONE merged table: exact 7 headers in order, 7 rows x 7 cells,
 *          single ui/table.
 *   P1F-2  registry controls preserved: 7 global Switches (PATCH + pending),
 *          Search/Fetch segments (local-only), P1..P7 ranks + arrow boundaries.
 *   P1F-3  endpoint/health per row: stripped Endpoint, Health dot+label, no
 *          Quota/p95 columns (telemetry drill-down lives in the modal +
 *          Usage view), no Breaker column or Trip/Reset buttons.
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
 *   P1F-7  960 scroll: Table min-w-[960px] inside the overflow-x-auto
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
const settingsSource = readFileSync(path.resolve(testDir, "./SettingsProviders.tsx"), "utf8")
// Slice 4: row/modal siblings own their sources; assertions run against the
// new owners plus the union of the registry feature owners.
const settingsModalSource = readFileSync(
  path.resolve(testDir, "./ProviderTestModal.tsx"),
  "utf8"
)
const removedModalShimPath = path.resolve(testDir, "../common/Modal.tsx")
const removedDialogShimPath = path.resolve(testDir, "../ui/dialog.tsx")
const removedTableShimPath = path.resolve(testDir, "../ui/table.tsx")
const settingsFeatureSource = [
  settingsSource,
  settingsModalSource,
  readFileSync(path.resolve(testDir, "./ProviderRegistryRow.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderRegistryHeader.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderHealthStatus.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderPriorityControl.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderRowPill.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderOperationControl.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./providerDisplay.ts"), "utf8"),
].join("\n")
const appSource = readFileSync(path.resolve(testDir, "../../App.tsx"), "utf8")
const dashboardShellSource = readFileSync(
  path.resolve(testDir, "../../app/DashboardShell.tsx"),
  "utf8"
)
const sidebarSource = readFileSync(
  path.resolve(testDir, "../layout/Sidebar.tsx"),
  "utf8"
)
const routesNavSource = readFileSync(
  path.resolve(testDir, "../../app/layout/SidebarNavList.tsx"),
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
  "Tinyfish",
] as const

const EXPECTED_MERGED_HEADERS = [
  "Provider",
  "Endpoint",
  "Health",
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

async function renderAppAt(route: string): Promise<FetchStub> {
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
  // PersistGate opens asynchronously by design; the redirect target asserts
  // only after the shell is mounted.
  await screen.findByRole("navigation", { name: "Primary" })
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
// P1F-1: ONE merged table with the exact 7 headers
// ---------------------------------------------------------------------------

describe("P1F-1: Settings registry is ONE merged table with 7 columns", () => {
  it("exposes the exact merged headers in order", async () => {
    renderSettings()
    await waitForProviders()
    expect(headerNames()).toEqual([...EXPECTED_MERGED_HEADERS])
  })

  it("renders a single table with 7 body rows", async () => {
    renderSettings()
    await waitForProviders()
    expect(screen.getAllByRole("table")).toHaveLength(1)
    expect(mergedTable().querySelectorAll("tbody tr")).toHaveLength(8)
    for (const name of SEED_PROVIDER_NAMES) {
      expect(findProviderRowTr(name)).toBeInTheDocument()
    }
  })

  it("gives every body row exactly 7 cells (merged columns never collapse)", async () => {
    renderSettings()
    await waitForProviders()
    const rows = Array.from(mergedTable().querySelectorAll("tbody tr"))
    expect(rows).toHaveLength(8)
    for (const row of rows) {
      expect(row.children).toHaveLength(EXPECTED_MERGED_HEADERS.length)
    }
  })

  it("reuses ui/table primitives for the merged table", () => {
    expect(settingsFeatureSource).toContain('from "@/shared/ui/table"')
    // Old ui path was a compat shim over the shared owner (removed in CLEANUP 1.1).
    expect(existsSync(removedTableShimPath)).toBe(false)
    for (const symbol of ["Table", "TableHeader", "TableBody", "TableRow", "TableHead", "TableCell"]) {
      expect(settingsFeatureSource, `SettingsProviders must reuse ${symbol}`).toContain(symbol)
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
    // 7-col header must exist AND the 7 switches must sit in Global cells.
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
    for (let rank = 1; rank <= 8; rank += 1) {
      expect(screen.getByText(`P${rank}`, { exact: true })).toBeInTheDocument()
    }
    expect(screen.queryByText("P100", { exact: true })).toBeNull()
    expect(
      screen.getByRole("button", { name: "Move Brave Search priority up" })
    ).toBeDisabled()
    expect(
      screen.getByRole("button", { name: "Move Tinyfish priority down" })
    ).toBeDisabled()
  })
})

// ---------------------------------------------------------------------------
// P1F-3: endpoint/health per row, quota/p95 in modal + Usage (RED)
// ---------------------------------------------------------------------------

describe("P1F-3: endpoint/health ride in the merged row", () => {
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

  it("does not render Quota or p95 as registry columns (telemetry lives in the modal + Usage view)", async () => {
    renderSettings()
    await waitForProviders()
    expect(headerNames()).not.toContain("Quota")
    expect(headerNames()).not.toContain("p95")
    expect(headerNames()).toEqual([...EXPECTED_MERGED_HEADERS])
    const rows = Array.from(mergedTable().querySelectorAll("tbody tr"))
    expect(rows).toHaveLength(8)
    for (const row of rows) {
      expect(row.children).toHaveLength(EXPECTED_MERGED_HEADERS.length)
    }
  })

  it("keeps quota/p95 drill-down in the test modal (not in row cells)", async () => {
    const user = userEvent.setup()
    renderSettings()
    await waitForProviders()
    await user.click(testIconFor("Brave Search"))
    const dialog = await screen.findByRole("dialog")
    expect(dialog.textContent).toMatch(/\d+ms|—/)
    expect(dialog.textContent).not.toContain("∞")
  })

  it("does not expose a Breaker column or Trip/Reset buttons", async () => {
    renderSettings()
    await waitForProviders()
    expect(screen.queryByText("Breaker")).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Trip" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Reset" })).not.toBeInTheDocument()
  })

  it("keeps row cells left-aligned with no right-aligned drift", async () => {
    renderSettings()
    await waitForProviders()
    const health = cellFor("Brave Search", "Health")
    const test = cellFor("Brave Search", "Test")
    expect(health.className).not.toContain("text-right")
    expect(test.className).not.toContain("text-right")
  })
})

// ---------------------------------------------------------------------------
// P1F-4: icon-opened ProviderTestModal (RED)
// ---------------------------------------------------------------------------

describe("P1F-4: icon opens the ProviderTestModal (never fetches on open)", () => {
  it("declares the ProviderTestModal on a Modal/Dialog wrapper in source", () => {
    expect(settingsModalSource).toContain("ProviderTestModal")
    // The page renders the extracted modal sibling.
    expect(settingsSource).toContain("ProviderTestModal")
    expect(
      settingsModalSource.includes("@/shared/ui/Modal") ||
        settingsModalSource.includes("@/shared/ui/dialog") ||
        settingsModalSource.includes("from \"@/shared/ui/dialog\"")
    ).toBe(true)
    // Old Modal/Dialog paths were compat shims over the shared owners (removed in CLEANUP 1.1).
    expect(existsSync(removedModalShimPath)).toBe(false)
    expect(existsSync(removedDialogShimPath)).toBe(false)
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
    // RF2: null limits stay blank/emdash (infinity retired). Brave with no
    // snapshot shows its honest unavailable message; Tavily renders the
    // blank native form, so the em-dash blank is pinned on Tavily.
    expect(dialog.textContent).not.toContain("∞")
    await user.keyboard("{Escape}")
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    })
    await user.click(testIconFor("Tavily"))
    const tavilyDialog = await screen.findByRole("dialog")
    expect(tavilyDialog.textContent).toContain("—/—")
    expect(tavilyDialog.textContent).not.toContain("∞")

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
    expect(settingsFeatureSource).not.toMatch(/Total fleet/)
    expect(settingsFeatureSource).not.toMatch(/Fleet avg latency/)
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
    expect(settingsFeatureSource).not.toMatch(/Provider filter/)
  })
})

// ---------------------------------------------------------------------------
// P1F-6: standalone Providers page retired (source contract, RED)
// ---------------------------------------------------------------------------

describe("P1F-6: Providers page retired — redirect + no providers nav", () => {
  it("App drops the ProviderMatrix route and redirects /providers -> /settings", () => {
    expect(dashboardShellSource).not.toMatch(/ProviderMatrix/)
    expect(appSource).not.toMatch(/ProviderMatrix/)
    // Thin App shim renders the shell that owns the redirect.
    expect(appSource).toContain("DashboardShell")
    expect(dashboardShellSource).toContain('path="/providers"')
    const idx = dashboardShellSource.indexOf('path="/providers"')
    const window_ = dashboardShellSource.slice(idx, idx + 300)
    expect(window_, "/providers must Navigate to /settings").toMatch(/Navigate/)
    expect(window_, "/providers must Navigate to /settings").toContain("/settings")
  })

  it("Sidebar drops the providers TabId, nav item, and route target", () => {
    expect(routesNavSource).not.toContain('"providers"')
    expect(routesNavSource).not.toContain('"/providers"')
    expect(sidebarSource).not.toContain('"providers"')
    expect(sidebarSource).not.toContain('"/providers"')
    // Compat shim keeps the old sidebar import surface working.
    expect(sidebarSource).toMatch(/from\s+["']@\/app\/layout\/Sidebar["']/)
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
      expect(settingsFeatureSource, `merged table must carry ${marker}`).toContain(marker)
    }
  })
})

// ---------------------------------------------------------------------------
// P1F-7: min-w-1280 horizontal scroll (RED)
// ---------------------------------------------------------------------------

describe("P1F-7: merged table scrolls horizontally from 960px", () => {
  it("Table carries min-w-[960px] inside the overflow-x-auto scroller", async () => {
    renderSettings()
    await waitForProviders()
    const table = mergedTable()
    expect(table.className).toMatch(/min-w-\[960px\]/)
    const container = table.closest('[data-slot="table-container"]') as HTMLElement | null
    expect(container, "ui/table scroller must wrap the merged table").not.toBeNull()
    expect(container!.className).toMatch(/overflow-x-auto/)
  })

  it("merged header + body cells keep nowrap (no wrapping)", async () => {
    renderSettings()
    await waitForProviders()
    const cells = Array.from(mergedTable().querySelectorAll("th, td")) as HTMLElement[]
    expect(cells.length).toBe(EXPECTED_MERGED_HEADERS.length + 8 * EXPECTED_MERGED_HEADERS.length)
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
    await renderAppAt("/providers")
    await waitFor(
      () => {
        expect(screen.getByRole("heading", { name: "Settings" })).toBeInTheDocument()
      },
      { timeout: 5000 }
    )
    expect(screen.getByTestId("test-location").textContent).toBe("/settings")
  })

  it("the redirect target shows the merged registry (7 headers, no Providers view)", async () => {
    await renderAppAt("/providers")
    await waitFor(
      () => {
        expect(screen.getByRole("heading", { name: "Settings" })).toBeInTheDocument()
      },
      { timeout: 5000 }
    )
    expect(headerNames()).toEqual([...EXPECTED_MERGED_HEADERS])
    expect(screen.queryByRole("heading", { name: "Providers" })).not.toBeInTheDocument()
  })
})
})

describe("SettingsProviders.s-p1.test.tsx", () => {

/**
 * S-P1 Settings Providers alignment — BDD Acceptance (RED phase).
 *
 * User bullet (verbatim): "Inconsistent alignment with the fields. I think it's
 * better to use some kind of a table so all the elements are aligned. Here is a
 * good example." BUG image.png shows staggered Global/Search/Fetch/Test
 * controls (flex-wrap rows drift with provider-name width); GOOD EXAMPLE
 * image-1.png shows a single shared table with aligned columns.
 *
 * Plan under test (ONLY SettingsProviders.tsx):
 *   flex-wrap list -> ui/table (Table/Header/Body/Row/Head/Cell, reuse as-is)
 *   with columns Provider|Global|Search|Fetch|Test;
 *   OperationControl null -> placeholder so columns never collapse;
 *   all contracts preserved (priority, Switch, SegmentedControl On/Off,
 *   Not-supported, Test states). NO page merge (P1 separate). freesearch-ui/ ONLY.
 *
 * AC mapping (P1-FINAL: merged 7-column table):
 *   S-P1-1  registry renders as ui/table with columns
 *           Provider|Endpoint|Health|Test|Search|Fetch|Global
 *           in order (Table/Header/Body/Row/Head/Cell reuse as-is;
 *           flex-wrap list gone).
 *   S-P1-2  per-column x-position equality across 7 rows (<=1px): single shared
 *           <table>, uniform 10-cell rows, nowrap cells. jsdom has no layout
 *           engine so getBoundingClientRect() is 0 there; the executable proxy
 *           is the structural invariant (shared table + identical column index
 *           + whitespace-nowrap) PLUS a literal left-delta measurement gated on
 *           the table existing. Real sub-pixel proof needs a browser (Playwright).
 *   S-P1-3  Global-off placeholder no-shift: OperationControl never returns
 *           null — unsupported+globally-disabled renders a placeholder cell so
 *           Search/Fetch columns never collapse (Brave fetch; Parallel is fetch-capable).
 *   S-P1-4  375px scroll-no-wrap: table container scrolls horizontally
 *           (overflow-x-auto) with nowrap cells; no wrapping, no flex-wrap.
 *   S-P1-5  contracts preserved: priority P1..P7 + up/down boundaries, global
 *           Switch (aria-label + PATCH + pending disabled), SegmentedControl
 *           On/Off (aria-label + aria-pressed + local-only), Not-supported guard,
 *           icon test button per row (aria-label + modal open, zero fetch) +
 *           modal Test states (Test/Testing... + POST).
 *   S-P1-6  regression guards (must stay GREEN before and after): Settings
 *           pills (Providers/Keys/Failover, pill variant, no line), URL/sidebar/
 *           theme (C1/C2R/C3R/C4 baseline), ProviderMatrix untouched, NO page
 *           merge (SettingsProviders never imports ProviderMatrix).
 *
 * RED expectation (current baseline: div flex-wrap list, OperationControl
 * returns null when globallyDisabled && !supported):
 *   S-P1-1..S-P1-5 FAIL cleanly (no <table>, no <tr>, bare `return null`,
 *   flex-wrap still present). S-P1-6 PASSES (baseline intact).
 *
 * P1-FINAL sweep: the registry is now the merged 7-column table
 *   Provider|Endpoint|Health|Test|Search|Fetch|Global
 *   (registry controls + endpoint/health telemetry, min-w-960 scroll) with an
 *   icon-opened ProviderTestModal. All counts/headers below track FINAL.
 */

const testDir = import.meta.dirname
const settingsSource = readFileSync(path.resolve(testDir, "./SettingsProviders.tsx"), "utf8")
// Slice 4: registry siblings own rows/header/modal/controls; assertions run
// against the union of the feature owners plus shim-compat pins.
const settingsFeatureSource = [
  settingsSource,
  readFileSync(path.resolve(testDir, "./ProviderRegistryRow.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderRegistryHeader.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderTestModal.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderTestModalDetail.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderHealthStatus.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderPriorityControl.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderRowPill.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderOperationControl.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./providerDisplay.ts"), "utf8"),
].join("\n")
const tableSource = readFileSync(path.resolve(testDir, "../../shared/ui/table.tsx"), "utf8")
const removedTableShimPath = path.resolve(testDir, "../ui/table.tsx")
// P1-FINAL (blessed inversion): ProviderMatrix.tsx is DELETED by the merge —
// no test may read it (the file is gone Green). Fleet-telemetry pins live in
// SettingsProviders.p1-final.test.tsx.
const appSource = readFileSync(path.resolve(testDir, "../../App.tsx"), "utf8")
const routesSource = readFileSync(path.resolve(testDir, "../../app/routes.ts"), "utf8")
const dashboardShellSource = readFileSync(
  path.resolve(testDir, "../../app/DashboardShell.tsx"),
  "utf8"
)
const sidebarSource = readFileSync(path.resolve(testDir, "../layout/Sidebar.tsx"), "utf8")
const routesNavSource = readFileSync(
  path.resolve(testDir, "../../app/layout/SidebarNavList.tsx"),
  "utf8"
)
const indexCssSource = readFileSync(path.resolve(testDir, "../../index.css"), "utf8")

const norm = (value: string): string => value.toLowerCase().replace(/\s+/g, "")

const SEED_PROVIDER_NAMES = [
  "Brave Search",
  "Keenable",
  "Tavily",
  "Exa",
  "Firecrawl",
  "You.com",
  "Parallel",
  "Tinyfish",
] as const

const FETCH_UNSUPPORTED = ["Brave Search"] as const
const FETCH_SUPPORTED = ["Keenable", "Tavily", "Exa", "Firecrawl", "You.com", "Parallel", "Tinyfish"] as const

const EXPECTED_HEADERS = [
  "Provider",
  "Endpoint",
  "Health",
  "Test",
  "Search",
  "Fetch",
  "Global",
] as const

let patchGate: Promise<Response> | null = null
let testGate: Promise<Response> | null = null

function renderSettings(): FetchStub {
  patchGate = null
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
      if (patchGate) return patchGate
      const backendId = req.url.split("/").at(-1) ?? "unknown"
      const wire = allProvidersFixture().find((p) => p.provider_id === backendId)
      return ok({ ...(wire ?? allProvidersFixture()[0]), ...((req.body as object) ?? {}) })
    }
    if (req.method === "POST" && req.url.endsWith("/test")) {
      if (testGate) return testGate
      return ok({
        provider: "x",
        ok: true,
        status: "healthy",
        latency_ms: 142,
        checked_at: "2026-09-06T10:04:00Z",
        detail: null,
      })
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

async function waitForProviders() {
  await waitFor(() => {
    expect(screen.getByText("Brave Search", { exact: true })).toBeInTheDocument()
  })
}

/**
 * TR-STRICT row lookup (S-P1 required traversal). Throws Red when rows are
 * still <div>s — that throw IS the Red signal for the tr-traversal update.
 */
function findProviderRowTr(provider: string): HTMLTableRowElement {
  const nameEl = screen.getByText(provider, { exact: true })
  const tr = nameEl.closest("tr")
  if (!tr) {
    throw new Error(
      `Provider table row <tr> not found for ${provider} — S-P1 table migration missing (rows are still divs)`
    )
  }
  return tr as HTMLTableRowElement
}

function providerTable(): HTMLElement {
  return screen.getByRole("table")
}

function headerNames(): string[] {
  const table = providerTable()
  return Array.from(table.querySelectorAll("thead th")).map(
    (th) => th.textContent?.trim() ?? ""
  )
}

function columnIndex(header: string): number {
  const idx = headerNames().indexOf(header)
  if (idx < 0) throw new Error(`Table header not found: ${header} (got [${headerNames()}])`)
  return idx
}

function cellFor(provider: string, header: string): HTMLElement {
  const row = findProviderRowTr(provider)
  const idx = columnIndex(header)
  const cell = row.children[idx] as HTMLElement | undefined
  if (!cell) throw new Error(`Cell ${header} (index ${idx}) missing in row ${provider}`)
  return cell
}

function columnLefts(table: HTMLElement, colIdx: number): number[] {
  const rows = Array.from(table.querySelectorAll("tbody tr"))
  return rows.map((row) => {
    const cell = row.children[colIdx] as HTMLElement
    return cell.getBoundingClientRect().left
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

// ---------------------------------------------------------------------------
// S-P1-1: table structure + ui/table reuse
// ---------------------------------------------------------------------------

describe("S-P1-1: registry is a ui/table with the merged 7 columns", () => {
  it("reuses ui/table primitives as-is (Table/Header/Body/Row/Head/Cell import)", () => {
    expect(settingsFeatureSource).toContain('from "@/shared/ui/table"')
    // Old ui path was a compat shim over the shared owner (removed in CLEANUP 1.1).
    expect(existsSync(removedTableShimPath)).toBe(false)
    for (const symbol of [
      "Table",
      "TableHeader",
      "TableBody",
      "TableRow",
      "TableHead",
      "TableCell",
    ]) {
      expect(settingsFeatureSource, `SettingsProviders must reuse ${symbol}`).toContain(symbol)
    }
  })

  it("ui/table still exports the reused primitives (reuse as-is, no fork)", () => {
    for (const symbol of [
      "function Table(",
      "function TableHeader(",
      "function TableBody(",
      "function TableRow(",
      "function TableHead(",
      "function TableCell(",
    ]) {
      expect(tableSource, `ui/table must still define ${symbol}`).toContain(symbol)
    }
  })

  it("flex-wrap list is gone (no flex-wrap rows, no basis-48 drift)", () => {
    expect(settingsFeatureSource.includes("flex-wrap")).toBe(false)
    expect(settingsFeatureSource.includes("basis-48")).toBe(false)
  })

  it("renders exactly one table for the provider registry", async () => {
    renderSettings()
    await waitForProviders()
    expect(screen.getAllByRole("table")).toHaveLength(1)
  })

  it("exposes the seven merged headers in exact order", async () => {
    renderSettings()
    await waitForProviders()
    expect(headerNames()).toEqual([...EXPECTED_HEADERS])
  })

  it("renders 7 body rows (one per backend provider)", async () => {
    renderSettings()
    await waitForProviders()
    const rows = providerTable().querySelectorAll("tbody tr")
    expect(rows).toHaveLength(8)
    for (const name of SEED_PROVIDER_NAMES) {
      expect(findProviderRowTr(name)).toBeInTheDocument()
    }
  })

  it("gives every body row exactly 7 cells (columns never collapse)", async () => {
    renderSettings()
    await waitForProviders()
    const rows = Array.from(providerTable().querySelectorAll("tbody tr"))
    expect(rows).toHaveLength(8)
    for (const row of rows) {
      expect(row.children).toHaveLength(EXPECTED_HEADERS.length)
    }
  })
})

// ---------------------------------------------------------------------------
// S-P1-2: per-column x-position equality (<=1px across 7 rows)
// ---------------------------------------------------------------------------

describe("S-P1-2: per-column x-position equality across 7 rows (<=1px)", () => {
  it("structural invariant: shared table + uniform columns + nowrap cells", async () => {
    renderSettings()
    await waitForProviders()
    const table = providerTable()
    const rows = Array.from(table.querySelectorAll("tbody tr"))
    expect(rows).toHaveLength(8)
    // Every row lives in the SAME table/tbody (single column grid).
    for (const row of rows) {
      expect(row.closest("table")).toBe(table)
      expect(row.children).toHaveLength(EXPECTED_HEADERS.length)
    }
    // Nowrap cells: ui/table TableHead/TableCell carry whitespace-nowrap.
    const cells = Array.from(table.querySelectorAll("th, td")) as HTMLElement[]
    expect(cells.length).toBe(EXPECTED_HEADERS.length + 8 * EXPECTED_HEADERS.length)
    for (const cell of cells) {
      expect(cell.className).toMatch(/whitespace-nowrap/)
    }
  })

  it("measured left edges match within 1px per column across all 7 rows", async () => {
    renderSettings()
    await waitForProviders()
    const table = providerTable()
    for (let col = 0; col < EXPECTED_HEADERS.length; col += 1) {
      const lefts = columnLefts(table, col)
      expect(lefts).toHaveLength(8)
      for (const left of lefts) {
        expect(Number.isFinite(left)).toBe(true)
      }
      const delta = Math.max(...lefts) - Math.min(...lefts)
      expect(delta, `column ${EXPECTED_HEADERS[col]} left delta must be <=1px`).toBeLessThanOrEqual(1)
    }
  })
})

// ---------------------------------------------------------------------------
// S-P1-3: Global-off placeholder no-shift
// ---------------------------------------------------------------------------

describe("S-P1-3: Global-off placeholder keeps columns from collapsing", () => {
  it("OperationControl never returns null (placeholder keeps the cell occupied)", () => {
    expect(settingsFeatureSource).not.toMatch(/if\s*\(\s*globallyDisabled\s*\)\s*return\s+null/)
  })

  it("unsupported fetch shows a disabled switch with tooltip while Global is on (Brave)", async () => {
    renderSettings()
    await waitForProviders()
    for (const name of FETCH_UNSUPPORTED) {
      const fetchCell = cellFor(name, "Fetch")
      const switchEl = within(fetchCell).getByRole("switch")
      expect(switchEl).toBeDisabled()
      expect(switchEl).toHaveAttribute("aria-checked", "false")
      expect(switchEl).toHaveAttribute(
        "aria-label",
        `${name} fetch routing (not supported)`
      )
    }
  })

  it("supported fetch shows an active switch while Global is on", async () => {
    renderSettings()
    await waitForProviders()
    for (const name of FETCH_SUPPORTED) {
      const fetchCell = cellFor(name, "Fetch")
      expect(
        within(fetchCell).getByRole("switch", { name: `${name} fetch routing` })
      ).toBeInTheDocument()
    }
  })

  it("toggling Global off keeps all 7 cells with a non-empty Fetch placeholder (no-shift)", async () => {
    const user = userEvent.setup()
    const stub = renderSettings()
    await waitForProviders()

    const before = cellFor("Brave Search", "Fetch")
    const beforeLeft = before.getBoundingClientRect().left
    expect(Number.isFinite(beforeLeft)).toBe(true)

    await user.click(
      screen.getByRole("switch", { name: "Brave Search global routing" })
    )
    await waitFor(() => {
      expect(
        screen.getByRole("switch", { name: "Brave Search global routing" })
      ).toHaveAttribute("aria-checked", "false")
    })
    const patches = stub.requestsTo("/api/v1/providers/brave")
    expect(patches).toHaveLength(1)
    expect(patches[0].body).toEqual({ enabled: false })

    // Columns never collapse: still 7 cells, Fetch still occupied.
    const row = findProviderRowTr("Brave Search")
    expect(row.children).toHaveLength(EXPECTED_HEADERS.length)
    const fetchCell = cellFor("Brave Search", "Fetch")
    expect(within(fetchCell).getByRole("switch")).toBeDisabled()
    const afterLeft = fetchCell.getBoundingClientRect().left
    expect(Math.abs(afterLeft - beforeLeft)).toBeLessThanOrEqual(1)
  })
})

// ---------------------------------------------------------------------------
// S-P1-4: 375px scroll-no-wrap
// ---------------------------------------------------------------------------

describe("S-P1-4: 375px viewport scrolls horizontally without wrapping", () => {
  it("table container is the ui/table overflow-x-auto scroller", async () => {
    renderSettings()
    await waitForProviders()
    const table = providerTable()
    const container = table.closest('[data-slot="table-container"]') as HTMLElement | null
    expect(container, "ui/table container [data-slot=table-container] must wrap the table").not.toBeNull()
    expect(container!.className).toMatch(/overflow-x-auto/)
    expect(container!.className).toMatch(/w-full/)
    expect(table.className).toMatch(/w-full/)
  })

  it("narrow viewport keeps nowrap cells inside a horizontal scroller (375px)", async () => {
    ;(window.innerWidth as number) = 375
    window.dispatchEvent(new Event("resize"))
    renderSettings()
    await waitForProviders()
    const table = providerTable()
    const container = table.closest('[data-slot="table-container"]') as HTMLElement
    expect(container.className).toMatch(/overflow-x-auto/)
    const cells = Array.from(table.querySelectorAll("th, td")) as HTMLElement[]
    expect(cells.length).toBe(EXPECTED_HEADERS.length + 8 * EXPECTED_HEADERS.length)
    for (const cell of cells) {
      expect(cell.className).toMatch(/whitespace-nowrap/)
    }
    // No wrapping list remains in the migrated source.
    expect(settingsFeatureSource.includes("flex-wrap")).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// S-P1-5: contracts preserved (priority, Switch, SegmentedControl, guards, Test)
// ---------------------------------------------------------------------------

describe("S-P1-5: all SettingsProviders contracts preserved in the table", () => {
  it("shows priorities P1..P7 with bounded up/down controls per row", async () => {
    renderSettings()
    await waitForProviders()
    for (let priority = 1; priority <= 8; priority += 1) {
      expect(screen.getByText(`P${priority}`, { exact: true })).toBeInTheDocument()
    }
    for (const name of SEED_PROVIDER_NAMES) {
      expect(
        screen.getByRole("button", { name: `Move ${name} priority up` })
      ).toBeInTheDocument()
      expect(
        screen.getByRole("button", { name: `Move ${name} priority down` })
      ).toBeInTheDocument()
    }
    // Boundaries come from sorted priority: first row cannot move up, last cannot move down.
    expect(
      screen.getByRole("button", { name: "Move Brave Search priority up" })
    ).toBeDisabled()
    expect(
      screen.getByRole("button", { name: "Move Tinyfish priority down" })
    ).toBeDisabled()
    expect(
      screen.getByRole("button", { name: "Move Brave Search priority down" })
    ).not.toBeDisabled()
    expect(
      screen.getByRole("button", { name: "Move Parallel priority up" })
    ).not.toBeDisabled()
  })

  it("keeps 7 global Switches with provider-qualified labels", async () => {
    renderSettings()
    await waitForProviders()
    for (const name of SEED_PROVIDER_NAMES) {
      expect(
        screen.getByRole("switch", { name: `${name} global routing` })
      ).toBeInTheDocument()
    }
  })

  it("persists a global toggle via PATCH and disables the switch while pending", async () => {
    const user = userEvent.setup()
    const gate = deferred<Response>()
    const stub = renderSettings()
    await waitForProviders()
    patchGate = gate.promise

    await user.click(screen.getByRole("switch", { name: "Exa global routing" }))
    await waitFor(() => {
      expect(screen.getByRole("switch", { name: "Exa global routing" })).toBeDisabled()
    })

    gate.resolve(ok({ ...allProvidersFixture()[3], enabled: false }))
    await waitFor(() => {
      expect(screen.getByRole("switch", { name: "Exa global routing" })).toHaveAttribute(
        "aria-checked",
        "false"
      )
    })
    const patches = stub.requestsTo("/api/v1/providers/exa")
    expect(patches).toHaveLength(1)
    expect(patches[0].body).toEqual({ enabled: false })
  })

  it("keeps Search switch local-only with exclusive aria-checked", async () => {
    const user = userEvent.setup()
    const stub = renderSettings()
    await waitForProviders()

    const searchCell = cellFor("Brave Search", "Search")
    const searchSwitch = within(searchCell).getByRole("switch", {
      name: "Brave Search search routing",
    })
    expect(searchSwitch).toHaveAttribute("aria-checked", "true")
    await user.click(searchSwitch)
    expect(searchSwitch).toHaveAttribute("aria-checked", "false")
    expect(stub.requests.filter((r) => r.method === "PATCH")).toHaveLength(0)
  })

  it("keeps Fetch switch local-only with exclusive aria-checked", async () => {
    const user = userEvent.setup()
    const stub = renderSettings()
    await waitForProviders()

    const fetchCell = cellFor("Tavily", "Fetch")
    const fetchSwitch = within(fetchCell).getByRole("switch", {
      name: "Tavily fetch routing",
    })
    expect(fetchSwitch).toHaveAttribute("aria-checked", "true")
    await user.click(fetchSwitch)
    expect(fetchSwitch).toHaveAttribute("aria-checked", "false")
    expect(stub.requests.filter((r) => r.method === "PATCH")).toHaveLength(0)
  })

  it("exposes an icon test button per row that opens the modal; modal Test runs handleTest (Testing... + POST)", async () => {
    const user = userEvent.setup()
    const gate = deferred<Response>()
    const stub = renderSettings()
    await waitForProviders()
    testGate = gate.promise

    // P1-FINAL: per-row Test affordance is an icon button that opens the
    // ProviderTestModal (never fetches on open).
    for (const name of SEED_PROVIDER_NAMES) {
      const row = findProviderRowTr(name)
      const testCell = row.children[columnIndex("Test")] as HTMLElement
      expect(
        within(testCell).getByRole("button", { name: `${name} test connection` })
      ).toBeInTheDocument()
    }
    const callsBefore = stub.requests.length
    await user.click(
      screen.getByRole("button", { name: "Brave Search test connection" })
    )
    const dialog = await screen.findByRole("dialog")
    expect(stub.requests.length).toBe(callsBefore)
    expect(stub.requestsTo("/api/v1/providers/brave/test")).toHaveLength(0)

    const modalTest = within(dialog).getByRole("button", { name: /test/i })
    expect(modalTest).toHaveTextContent("Test")
    await user.click(modalTest)
    await waitFor(() => {
      expect(
        within(screen.getByRole("dialog")).getByRole("button", { name: /testing/i })
      ).toBeInTheDocument()
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
      expect(screen.getByRole("dialog").textContent).toMatch(/142ms|healthy/)
    })
    const tests = stub.requestsTo("/api/v1/providers/brave/test")
    expect(tests).toHaveLength(1)
    expect(tests[0].method).toBe("POST")
  })
})

// ---------------------------------------------------------------------------
// S-P1-6: regression guards (baseline must not regress — GREEN in Red phase)
// ---------------------------------------------------------------------------

describe("S-P1-6: P1-FINAL merge guards (inverted — page merged, RED)", () => {
  it("Settings pills stay Providers/Keys/Failover on the pill variant", async () => {
    renderSettings()
    await waitForProviders()
    expect(screen.getAllByRole("tab")).toHaveLength(3)
    for (const label of ["Providers", "Keys", "Failover"]) {
      expect(screen.getByRole("tab", { name: new RegExp(`^${label}$`) })).toBeInTheDocument()
    }
    const pillList = document.querySelector('[data-slot="tabs-list"][data-variant="pill"]')
    expect(pillList, "pill tablist must exist").not.toBeNull()
    expect(
      within(pillList as HTMLElement)
        .getAllByRole("tab")
        .map((t) => t.textContent)
    ).toEqual(["Providers", "Keys", "Failover"])
    expect(
      document.querySelectorAll('[data-slot="tabs-list"][data-variant="line"]')
    ).toHaveLength(0)
  })

  it("Carbon Black theme tokens are untouched (#1e1e1e scale + #007acc signal)", () => {
    expect(norm(indexCssSource).includes("#1e1e1e")).toBe(true)
    expect(norm(indexCssSource).includes("#252526")).toBe(true)
    expect(norm(indexCssSource).includes("#3e3e42")).toBe(true)
    expect(norm(indexCssSource).includes("#007acc")).toBe(true)
    expect(norm(indexCssSource).includes("oklch(")).toBe(false)
  })

  it("P1-FINAL route table: five workspace routes + /providers -> /settings redirect", () => {
    for (const routePath of [
      "/playground",
      "/routing",
      "/usage",
      "/activity",
      "/settings",
    ]) {
      expect(routesSource).toContain(`"${routePath}"`)
    }
    expect(dashboardShellSource).toMatch(/<Routes/)
    expect(dashboardShellSource).not.toMatch(/ProviderMatrix/)
    expect(appSource).not.toMatch(/ProviderMatrix/)
    // Thin App shim renders the shell that owns the table.
    expect(appSource).toContain("DashboardShell")
    // Legacy path survives ONLY as a redirect into Settings.
    expect(dashboardShellSource).toContain('"/providers"')
    const idx = dashboardShellSource.indexOf('"/providers"')
    const window_ = dashboardShellSource.slice(Math.max(0, idx - 120), idx + 300)
    expect(window_).toMatch(/Navigate/)
    expect(window_).toContain('"/settings"')
    expect(routesSource).toMatch(/export\s+(type|interface)\s+TabId/)
    expect(routesNavSource.includes("<NavLink")).toBe(true)
    expect(routesNavSource).not.toContain('"providers"')
    expect(routesNavSource).not.toContain('"/providers"')
    // Compat shim keeps the old sidebar import surface working.
    expect(sidebarSource).toMatch(/from\s+["']@\/app\/layout\/Sidebar["']/)
    // Nav targets live in the app route table; the nav binds through it.
    const tabPathsBlock = routesSource.slice(
      routesSource.indexOf("TAB_PATHS"),
      routesSource.indexOf("WorkspaceRoute")
    )
    for (const [id, href] of [
      ["playground", "/playground"],
      ["routing", "/routing"],
      ["quotas", "/usage"],
      ["activity", "/activity"],
      ["settings", "/settings"],
    ]) {
      expect(tabPathsBlock).toContain(`"${href}"`)
      expect(tabPathsBlock).toMatch(new RegExp(`${id}:`))
    }
    expect(routesNavSource).toMatch(/to=\{TAB_PATHS\[id\]\}/)
  })

  it("P1-FINAL page merge: ProviderMatrix retired, fleet telemetry merged into SettingsProviders", () => {
    // Standalone fleet page is gone: no Trip/Reset matrix, no fleet filter,
    // no stat cards in a separate page — the merged registry carries them.
    for (const marker of ["Endpoint", "Health", "Quota", "p95", "ProviderTestModal"]) {
      expect(settingsFeatureSource, `merged registry must carry ${marker}`).toContain(marker)
    }
    expect(settingsFeatureSource).not.toMatch(/Total fleet/)
    expect(settingsFeatureSource).not.toMatch(/Provider filter/)
  })

  it("freesearch-ui ONLY: SettingsProviders imports no backend/python paths", () => {
    expect(settingsFeatureSource).not.toMatch(/\.py["']/)
    expect(settingsFeatureSource).not.toMatch(/src\/freesearch/)
  })
})
})

describe("SettingsProviders.s-p2.test.tsx", () => {

/**
 * S-P2 provider priority values — BDD Acceptance (RED phase).
 *
 * User bullet (verbatim): "These values don't make any sense". BUG image-2.png
 * shows every registry row labelled P100 with the up/down arrows clipped at
 * the card edge. Scout: the live backend returns priority 100 for ALL
 * providers, and the UI renders the raw value (`P{provider.priority}`), so
 * every row reads P100 and the indicator column has no width floor.
 *
 * Plan under test (freesearch-ui/ ONLY, no button restyle/space/merge):
 *   SettingsProviders rank display (P{rank 1..7} from sorted order, never raw
 *   P100) + tooltip dispatch order;
 *   FreeSearchContext moveProviderPriority tied-value branch (equal priorities
 *   -> PATCH distinct rank numbers);
 *   PriorityIndicator fixed min-w/shrink-0 + first-cell px-3 (no clipping,
 *   table + scroller intact).
 *
 * AC mapping:
 *   S-P2-1  all-100 stub renders ranks P1..P7 in row order, never P100
 *           (rank display, not raw priority).
 *   S-P2-2  rank follows sorted order: scrambled backend priorities still
 *           render P1..P7 top-to-bottom with the exact row->rank mapping, plus
 *           an exact `Dispatch order N of 7` tooltip per row.
 *   S-P2-3  clipping guards: PriorityIndicator keeps shrink-0 AND gains a
 *           min-w-* floor (non-zero width proxy — jsdom has no layout engine,
 *           same structural-invariant approach as S-P1-2), first-column cells
 *           keep px-3, and the ui/table scroller (overflow-x-auto + nowrap,
 *           single 7x5 table) stays intact.
 *   S-P2-4  arrows exist for all 7 rows with sorted-order boundaries on ties;
 *           a tie move PATCHes DISTINCT rank numbers (landed guard) AND the
 *           PATCH set must reproduce the EXACT adjacent transposition
 *           (direction-correct: rank-3 down -> rank 4, all other rows stable)
 *           both under (priority, provider_id) replay-sort and in the live
 *           post-move top-to-bottom DOM order — full-tie (all-100) plus a new
 *           partial-tie (some tied, some distinct) case; GET refresh + P1..P7
 *           label-set invariant kept.
 *   S-P2-5  scope guards (GREEN before and after): lucide ArrowUp/ArrowDown
 *           untouched (no button restyle), no ProviderMatrix merge, no
 *           backend/python imports, S-P1 table alignment intact.
 *
 * RED expectation (final review: rank display, tooltip, min-w floor, and
 * tied-value DISTINCT PATCH branch have landed — S-P2-1..S-P2-3 and the S-P2-4
 * PATCH-shape guard are GREEN):
 *   S-P2-4 tie-ORDER (replay-sort + exact post-move DOM order, full-tie and
 *   partial-tie) FAILS cleanly until Developer lands production
 *   normalization — the two-PATCH rank swap cannot reproduce the adjacent
 *   transposition while the untouched rows keep their raw values.
 *   S-P2-5 + boundary/scroller guards stay GREEN throughout.
 */

const testDir = import.meta.dirname
const settingsSource = readFileSync(path.resolve(testDir, "./SettingsProviders.tsx"), "utf8")
// Slice 4: PriorityIndicator owns its module; assertions run against the new
// owner plus the union of the registry feature owners.
const indicatorSource = readFileSync(
  path.resolve(testDir, "./ProviderPriorityControl.tsx"),
  "utf8"
)
const settingsFeatureSource = [
  settingsSource,
  indicatorSource,
  readFileSync(path.resolve(testDir, "./ProviderRegistryRow.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderRegistryHeader.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderTestModal.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderHealthStatus.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderRowPill.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderOperationControl.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./providerDisplay.ts"), "utf8"),
].join("\n")

const SEED_PROVIDER_NAMES = [
  "Brave Search",
  "Keenable",
  "Tavily",
  "Exa",
  "Firecrawl",
  "You.com",
  "Parallel",
  "Tinyfish",
] as const

const EXPECTED_RANKS = ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"] as const

/** Scrambled backend priorities: rank must come from sorted order, not raw. */
const SCRAMBLED_PRIORITIES: Record<string, number> = {
  brave: 30,
  keenable: 10,
  tavily: 50,
  exa: 20,
  firecrawl: 70,
  you: 40,
  parallel: 60,
  tinyfish: 80,
}

/** Expected row->rank mapping for the scrambled fixture (ascending sort). */
const SCRAMBLED_RANKS: Record<string, string> = {
  Keenable: "P1",
  Exa: "P2",
  "Brave Search": "P3",
  "You.com": "P4",
  Tavily: "P5",
  Parallel: "P6",
  Firecrawl: "P7",
  Tinyfish: "P8",
}

function all100Fixture(): WireProviderStatus[] {
  return allProvidersFixture().map((row) => ({ ...row, priority: 100 }))
}

function scrambledFixture(): WireProviderStatus[] {
  return allProvidersFixture().map((row) => ({
    ...row,
    priority: SCRAMBLED_PRIORITIES[row.provider_id] ?? row.priority,
  }))
}

/** Partial tie: brave:1, keenable:2, tavily/exa/firecrawl tied at 5, you:6, parallel:7. */
const PARTIAL_TIE_PRIORITIES: Record<string, number> = {
  brave: 1,
  keenable: 2,
  tavily: 5,
  exa: 5,
  firecrawl: 5,
  you: 6,
  parallel: 7,
  tinyfish: 8,
}

function partialTieFixture(): WireProviderStatus[] {
  return allProvidersFixture().map((row) => ({
    ...row,
    priority: PARTIAL_TIE_PRIORITIES[row.provider_id] ?? row.priority,
  }))
}

const PARTIAL_TIE_PRE_NAMES = [
  "Brave Search",
  "Keenable",
  "Tavily",
  "Exa",
  "Firecrawl",
  "You.com",
  "Parallel",
  "Tinyfish",
] as const

function renderSettingsWith(providers: WireProviderStatus[]): FetchStub {
  const server = providers.map((row) => ({ ...row }))
  const stub = installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(server)
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    if (req.method === "PATCH" && req.url.startsWith("/api/v1/providers/")) {
      const backendId = req.url.split("/").at(-1) ?? "unknown"
      const entry = server.find((row) => row.provider_id === backendId)
      if (!entry) return err(404, { detail: `unknown provider '${backendId}'` })
      Object.assign(entry, (req.body as object) ?? {})
      return ok(entry)
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

async function waitForProviders() {
  await waitFor(() => {
    expect(screen.getByText("Brave Search", { exact: true })).toBeInTheDocument()
  })
}

/**
 * TR-STRICT row lookup (same traversal contract as S-P1: every provider row
 * is a <tr>; throws when rows are still <div>s).
 */
function findProviderRowTr(provider: string): HTMLTableRowElement {
  const nameEl = screen.getByText(provider, { exact: true })
  const tr = nameEl.closest("tr")
  if (!tr) {
    throw new Error(
      `Provider table row <tr> not found for ${provider} — table migration missing`
    )
  }
  return tr as HTMLTableRowElement
}

/** The single P-rank label inside a provider row (works for P1..P7 AND P100). */
function priorityLabelInRow(row: HTMLTableRowElement): HTMLElement {
  const labels = Array.from(row.querySelectorAll("span")).filter((el) =>
    /^P\d+$/.test(el.textContent?.trim() ?? "")
  )
  if (labels.length !== 1) {
    throw new Error(
      `Expected exactly one P-rank label in row, found ${labels.length}: [${labels.map((l) => l.textContent).join(", ")}]`
    )
  }
  return labels[0] as HTMLElement
}

function rankOfRow(provider: string): string {
  return priorityLabelInRow(findProviderRowTr(provider)).textContent?.trim() ?? ""
}

/** Rank labels top-to-bottom in render order. */
function allRankLabelsInRowOrder(): string[] {
  const rows = Array.from(screen.getByRole("table").querySelectorAll("tbody tr"))
  return rows.map((row) => priorityLabelInRow(row as HTMLTableRowElement).textContent?.trim() ?? "")
}

function patchRequests(stub: FetchStub) {
  return stub.requests.filter(
    (r) => r.method === "PATCH" && r.url.startsWith("/api/v1/providers/")
  )
}

/** Provider display names top-to-bottom in render order. */
function providerNamesInRowOrder(): string[] {
  const rows = Array.from(screen.getByRole("table").querySelectorAll("tbody tr"))
  return rows.map((row) => {
    const nameEl = (row as HTMLTableRowElement).querySelector("span.font-medium")
    if (!nameEl) throw new Error("Provider name span.font-medium not found in table row")
    return nameEl.textContent?.trim() ?? ""
  })
}

/**
 * Replay a PATCH set onto a pre-move snapshot, then sort by
 * (priority, provider_id). The result must equal the expected adjacent
 * transposition. The pre-move snapshot is regenerated from the same pure
 * fixture the stub server was seeded with, so values are identical.
 */
function orderFromPatchSet(
  preMove: WireProviderStatus[],
  patches: Array<{ backendId: string; priority: number }>
): string[] {
  const priorityById = new Map(preMove.map((row) => [row.provider_id, row.priority]))
  for (const patch of patches) {
    if (!priorityById.has(patch.backendId)) {
      throw new Error(`PATCH for unknown provider '${patch.backendId}'`)
    }
    priorityById.set(patch.backendId, patch.priority)
  }
  return [...priorityById.entries()]
    .sort((a, b) => a[1] - b[1] || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))
    .map(([id]) => id)
}

function patchIdAndPriority(
  stub: FetchStub
): Array<{ backendId: string; priority: number }> {
  return patchRequests(stub).map((r) => ({
    backendId: r.url.split("/").at(-1) ?? "",
    priority: (r.body as { priority: number }).priority,
  }))
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

// ---------------------------------------------------------------------------
// S-P2-1: all-100 stub shows P1..P7, never P100
// ---------------------------------------------------------------------------

describe("S-P2-1: all-100 backend renders rank display P1..P7 (never raw P100)", () => {
  it("renders ranks P1..P7 top-to-bottom when every backend priority is 100", async () => {
    renderSettingsWith(all100Fixture())
    await waitForProviders()
    expect(allRankLabelsInRowOrder()).toEqual([...EXPECTED_RANKS])
  })

  it("shows each rank exactly once with zero P100 labels", async () => {
    renderSettingsWith(all100Fixture())
    await waitForProviders()
    for (let rank = 1; rank <= 8; rank += 1) {
      expect(screen.queryAllByText(`P${rank}`, { exact: true })).toHaveLength(1)
    }
    expect(screen.queryByText("P100", { exact: true })).toBeNull()
    const multiDigit = allRankLabelsInRowOrder().filter((label) => /^P\d{2,}$/.test(label))
    expect(multiDigit).toEqual([])
  })

  it("never renders the raw priority interpolation", () => {
    expect(indicatorSource).not.toContain("P{provider.priority}")
    // The page renders ranks through the extracted row sibling.
    expect(settingsSource).toContain("ProviderRegistryRow")
  })
})

// ---------------------------------------------------------------------------
// S-P2-2: rank follows sorted order + tooltip dispatch order
// ---------------------------------------------------------------------------

describe("S-P2-2: rank follows sorted order with dispatch-order tooltip", () => {
  it("maps scrambled backend priorities to ranks by ascending sorted order", async () => {
    renderSettingsWith(scrambledFixture())
    await waitForProviders()
    for (const [name, rank] of Object.entries(SCRAMBLED_RANKS)) {
      expect(rankOfRow(name)).toBe(rank)
    }
  })

  it("shows no raw backend values for the scrambled fixture", async () => {
    renderSettingsWith(scrambledFixture())
    await waitForProviders()
    expect(allRankLabelsInRowOrder()).toEqual([...EXPECTED_RANKS])
    for (const raw of ["P10", "P20", "P30", "P40", "P50", "P60", "P70", "P80"]) {
      expect(screen.queryByText(raw, { exact: true })).toBeNull()
    }
  })

  it("exposes an exact dispatch-order tooltip on every rank label", async () => {
    renderSettingsWith(all100Fixture())
    await waitForProviders()
    for (let rank = 1; rank <= 8; rank += 1) {
      const label = screen.getByText(`P${rank}`, { exact: true })
      expect(label.getAttribute("title")).toBe(`Dispatch order ${rank} of 8`)
    }
  })

  it("declares the dispatch-order tooltip in source", () => {
    expect(indicatorSource).toContain("Dispatch order")
  })

  it("derives arrow boundaries from sorted order on scrambled priorities", async () => {
    renderSettingsWith(scrambledFixture())
    await waitForProviders()
    // Sorted first = Keenable (10), sorted last = Firecrawl (70).
    expect(
      screen.getByRole("button", { name: "Move Keenable priority up" })
    ).toBeDisabled()
    expect(
      screen.getByRole("button", { name: "Move Tinyfish priority down" })
    ).toBeDisabled()
    expect(
      screen.getByRole("button", { name: "Move Keenable priority down" })
    ).not.toBeDisabled()
    expect(
      screen.getByRole("button", { name: "Move Firecrawl priority up" })
    ).not.toBeDisabled()
  })
})

// ---------------------------------------------------------------------------
// S-P2-3: clipping guards (min-w + shrink-0 + px-3, table + scroller intact)
// ---------------------------------------------------------------------------

describe("S-P2-3: priority indicator never clips at the card edge", () => {
  it("indicator keeps shrink-0 and gains a min-w-* floor (non-zero width proxy)", async () => {
    renderSettingsWith(all100Fixture())
    await waitForProviders()
    for (let rank = 1; rank <= 8; rank += 1) {
      const label = screen.getByText(`P${rank}`, { exact: true })
      const indicator = label.parentElement as HTMLElement | null
      expect(indicator, `P${rank} indicator wrapper must exist`).not.toBeNull()
      // shrink-0 stops flex compression; min-w-* floors the width so the
      // arrows + label cannot collapse to zero at the card edge. jsdom has
      // no layout engine, so the class invariant IS the executable guard
      // (same structural approach as S-P1-2); pixel proof needs a browser.
      expect(indicator!.className).toMatch(/shrink-0/)
      expect(indicator!.className).toMatch(/min-w-/)
    }
  })

  it("declares the min-w floor inside the PriorityIndicator source block", () => {
    expect(indicatorSource).toMatch(/shrink-0/)
    expect(indicatorSource).toMatch(/min-w-/)
  })

  it("first-column (Provider) cells keep px-3 breathing room", async () => {
    renderSettingsWith(all100Fixture())
    await waitForProviders()
    for (const name of SEED_PROVIDER_NAMES) {
      const row = findProviderRowTr(name)
      const firstCell = row.children[0] as HTMLElement
      expect(firstCell.tagName).toBe("TD")
      expect(firstCell.className).toMatch(/px-3/)
    }
  })

  it("table + scroller stay intact: single 7x7 merged table, overflow-x-auto, nowrap", async () => {
    renderSettingsWith(all100Fixture())
    await waitForProviders()
    expect(screen.getAllByRole("table")).toHaveLength(1)
    const table = screen.getByRole("table")
    expect(table.querySelectorAll("tbody tr")).toHaveLength(8)
    for (const row of Array.from(table.querySelectorAll("tbody tr"))) {
      expect(row.children).toHaveLength(7)
    }
    const container = table.closest('[data-slot="table-container"]') as HTMLElement | null
    expect(container, "ui/table scroller must wrap the table").not.toBeNull()
    expect(container!.className).toMatch(/overflow-x-auto/)
    const cells = Array.from(table.querySelectorAll("th, td")) as HTMLElement[]
    expect(cells.length).toBe(7 + 8 * 7)
    for (const cell of cells) {
      expect(cell.className).toMatch(/whitespace-nowrap/)
    }
  })
})

// ---------------------------------------------------------------------------
// S-P2-4: arrows + boundaries + PATCH distinct on ties + refresh
// ---------------------------------------------------------------------------

describe("S-P2-4: reorder arrows with tie-safe distinct PATCH + refresh", () => {
  it("renders up/down arrows for all 7 rows with boundaries on the all-100 stub", async () => {
    renderSettingsWith(all100Fixture())
    await waitForProviders()
    for (const name of SEED_PROVIDER_NAMES) {
      expect(
        screen.getByRole("button", { name: `Move ${name} priority up` })
      ).toBeInTheDocument()
      expect(
        screen.getByRole("button", { name: `Move ${name} priority down` })
      ).toBeInTheDocument()
    }
    // Stable sorted order keeps fixture order on ties: Brave first, Parallel last.
    expect(
      screen.getByRole("button", { name: "Move Brave Search priority up" })
    ).toBeDisabled()
    expect(
      screen.getByRole("button", { name: "Move Tinyfish priority down" })
    ).toBeDisabled()
    expect(
      screen.getByRole("button", { name: "Move Tavily priority up" })
    ).not.toBeDisabled()
    expect(
      screen.getByRole("button", { name: "Move Tavily priority down" })
    ).not.toBeDisabled()
  })

  it("a tie move PATCHes DISTINCT rank numbers (1..7, never 100) then refreshes", async () => {
    // Landed guard: the tied-value branch sends rank numbers, not the tied
    // raw value. Deliberately set-agnostic (no count/exact-value pin) so a
    // future full-renormalization (N PATCHes) still satisfies it — exact
    // order is pinned by the transposition tests below.
    const user = userEvent.setup()
    const stub = renderSettingsWith(all100Fixture())
    await waitForProviders()

    // Tavily sits at index 2 (rank 3); moving down swaps with Exa (rank 4).
    await user.click(screen.getByRole("button", { name: "Move Tavily priority down" }))

    await waitFor(() => {
      expect(patchRequests(stub).length).toBeGreaterThanOrEqual(2)
    })
    const values = patchIdAndPriority(stub).map((p) => p.priority)
    expect(values.length).toBeGreaterThan(0)
    for (const value of values) {
      expect(Number.isInteger(value)).toBe(true)
      expect(value).toBeGreaterThanOrEqual(1)
      expect(value).toBeLessThanOrEqual(8)
    }
    expect(new Set(values).size).toBe(values.length)
    expect(values).not.toContain(100)

    // Rank swap is followed by an authoritative GET refresh of the registry.
    await waitFor(() => {
      const gets = stub
        .requestsTo("/api/v1/providers")
        .filter((r) => r.method === "GET")
      expect(gets.length).toBeGreaterThanOrEqual(2)
    })

    // Rank display invariant survives the move: still exactly P1..P7.
    await waitFor(() => {
      expect([...allRankLabelsInRowOrder()].sort()).toEqual([...EXPECTED_RANKS])
    })
  })

  it("tie PATCH set reproduces the adjacent transposition under (priority, provider_id) sort", async () => {
    // Tavily (rank 3) moves down past Exa (rank 4): the ONLY correct
    // end-state is the adjacent transposition
    // [brave, keenable, exa, tavily, firecrawl, you, parallel].
    // Replaying the PATCH set onto the pre-move snapshot and sorting by
    // (priority, provider_id) must yield exactly that order. RED until
    // Developer lands normalization: the two-PATCH rank swap leaves the
    // untouched rows at 100, so the replay sorts the swapped pair first.
    const user = userEvent.setup()
    const stub = renderSettingsWith(all100Fixture())
    await waitForProviders()
    expect(providerNamesInRowOrder()).toEqual([
      "Brave Search",
      "Keenable",
      "Tavily",
      "Exa",
      "Firecrawl",
      "You.com",
      "Parallel",
      "Tinyfish",
    ])

    await user.click(screen.getByRole("button", { name: "Move Tavily priority down" }))

    await waitFor(() => {
      expect(patchRequests(stub).length).toBeGreaterThanOrEqual(2)
    })
    const replayed = orderFromPatchSet(all100Fixture(), patchIdAndPriority(stub))
    expect(replayed).toEqual([
      "brave",
      "keenable",
      "exa",
      "tavily",
      "firecrawl",
      "you",
      "parallel",
      "tinyfish",
    ])
  })

  it("tie move yields the exact transposed top-to-bottom order (direction-correct)", async () => {
    // Same move as above, asserted against the LIVE post-refresh DOM:
    // Tavily must read direction-correct at rank 4, Exa at rank 3, every
    // other row stable. RED until Developer lands normalization.
    const user = userEvent.setup()
    const stub = renderSettingsWith(all100Fixture())
    await waitForProviders()
    await user.click(screen.getByRole("button", { name: "Move Tavily priority down" }))

    // Quiescence first: authoritative GET refresh has landed...
    await waitFor(() => {
      const gets = stub
        .requestsTo("/api/v1/providers")
        .filter((r) => r.method === "GET")
      expect(gets.length).toBeGreaterThanOrEqual(2)
    })
    // ...then the registry must read as the adjacent transposition.
    await waitFor(() => {
      expect(providerNamesInRowOrder()).toEqual([
        "Brave Search",
        "Keenable",
        "Exa",
        "Tavily",
        "Firecrawl",
        "You.com",
        "Parallel",
        "Tinyfish",
      ])
    })
    expect(rankOfRow("Tavily")).toBe("P4")
    expect(rankOfRow("Exa")).toBe("P3")
  })

  it("partial-tie PATCH set reproduces the adjacent transposition under (priority, provider_id) sort", async () => {
    // Partial tie: brave:1, keenable:2, tavily/exa/firecrawl tied at 5,
    // you:6, parallel:7. Exa (rank 4) moves down past Firecrawl (rank 5):
    // the ONLY correct end-state is
    // [brave, keenable, tavily, firecrawl, exa, you, parallel].
    const user = userEvent.setup()
    const stub = renderSettingsWith(partialTieFixture())
    await waitForProviders()
    expect(providerNamesInRowOrder()).toEqual([...PARTIAL_TIE_PRE_NAMES])
    expect(rankOfRow("Tavily")).toBe("P3")
    expect(rankOfRow("Exa")).toBe("P4")
    expect(rankOfRow("Firecrawl")).toBe("P5")

    await user.click(screen.getByRole("button", { name: "Move Exa priority down" }))

    await waitFor(() => {
      expect(patchRequests(stub).length).toBeGreaterThanOrEqual(2)
    })
    const values = patchIdAndPriority(stub).map((p) => p.priority)
    expect(new Set(values).size).toBe(values.length)
    for (const value of values) {
      expect(Number.isInteger(value)).toBe(true)
      expect(value).toBeGreaterThanOrEqual(1)
      expect(value).toBeLessThanOrEqual(8)
    }
    const replayed = orderFromPatchSet(partialTieFixture(), patchIdAndPriority(stub))
    expect(replayed).toEqual([
      "brave",
      "keenable",
      "tavily",
      "firecrawl",
      "exa",
      "you",
      "parallel",
      "tinyfish",
    ])
  })

  it("partial-tie move yields the exact transposed top-to-bottom order", async () => {
    // Same partial-tie move, asserted against the LIVE post-refresh DOM:
    // Exa must read direction-correct at rank 5, Firecrawl at rank 4,
    // every other row stable. RED until Developer lands normalization.
    const user = userEvent.setup()
    const stub = renderSettingsWith(partialTieFixture())
    await waitForProviders()
    await user.click(screen.getByRole("button", { name: "Move Exa priority down" }))

    await waitFor(() => {
      const gets = stub
        .requestsTo("/api/v1/providers")
        .filter((r) => r.method === "GET")
      expect(gets.length).toBeGreaterThanOrEqual(2)
    })
    await waitFor(() => {
      expect(providerNamesInRowOrder()).toEqual([
        "Brave Search",
        "Keenable",
        "Tavily",
        "Firecrawl",
        "Exa",
        "You.com",
        "Parallel",
        "Tinyfish",
      ])
    })
    expect(rankOfRow("Exa")).toBe("P5")
    expect(rankOfRow("Firecrawl")).toBe("P4")
  })
})

// ---------------------------------------------------------------------------
// S-P2-5: scope guards — no button restyle/space/merge, freesearch-ui ONLY
// ---------------------------------------------------------------------------

describe("S-P2-5: no restyle, no merge, freesearch-ui only (stays green)", () => {
  it("keeps the lucide ArrowUp/ArrowDown controls with exact aria-labels", async () => {
    expect(indicatorSource).toContain("lucide-react")
    expect(indicatorSource).toContain("ArrowUp")
    expect(indicatorSource).toContain("ArrowDown")
    renderSettingsWith(all100Fixture())
    await waitForProviders()
    for (const name of SEED_PROVIDER_NAMES) {
      expect(
        screen.getByRole("button", { name: `Move ${name} priority up` })
      ).toBeInTheDocument()
      expect(
        screen.getByRole("button", { name: `Move ${name} priority down` })
      ).toBeInTheDocument()
    }
  })

  it("P1-FINAL page merge: fleet telemetry merged into SettingsProviders (ProviderMatrix retired)", () => {
    for (const marker of ["Endpoint", "Health", "Quota", "p95", "ProviderTestModal"]) {
      expect(settingsFeatureSource, `merged registry must carry ${marker}`).toContain(marker)
    }
  })

  it("freesearch-ui ONLY: no backend/python import paths", () => {
    expect(settingsFeatureSource).not.toMatch(/\.py["']/)
    expect(settingsFeatureSource).not.toMatch(/src\/freesearch/)
  })
})
})

describe("SettingsProviders.s-p3.test.tsx", () => {

/**
 * S-P3 Test buttons look like actual buttons â€” BDD Acceptance (RED phase).
 *
 * User bullet (verbatim): "Make these test buttons look like actual buttons."
 * Read-only: .agents/FEEDBACK/UI/feedback.md L22. SEE image yourself:
 * .agents/FEEDBACK/UI/image-3.png (Test plain text, no affordance).
 *
 * BUG image-3.png shows every registry row with a bare muted "Test" text
 * label at the far right â€” no border, no rounded box, no padding, no
 * data-slot="button". It reads as plain text, not an affordance.
 *
 * Plan under test (ONLY SettingsProviders.tsx Test cell):
 *   bare button -> ui/button outline sm OR Button-like Carbon classes;
 *   states Test/Testing...+disabled, aria-label unchanged, type=button;
 *   no other changes. freesearch-ui/ ONLY.
 *
 * AC mapping:
 *   S-P3-1  affordance â€” every Test button exposes a real button box:
 *           (ui/button: data-slot="button" + outline border) OR
 *           (Carbon button-like: border + rounded + padding), and is NOT
 *           plain muted text. RED: current Test cell is a bare <button>
 *           with `text-[13px] text-[var(--muted)] hover:text-white ...`
 *           and no border/rounded/padding/data-slot, so all affordance
 *           assertions FAIL cleanly.
 *   S-P3-2  states preserved â€” initial `Test` + type="button" + exact
 *           aria-label `{name} connection`; click flips to `Testing...` +
 *           disabled with aria-label/type stable; exactly one POST to
 *           /api/v1/providers/{id}/test; flips back to `Test` + enabled
 *           with aria-label stable. GREEN in Red phase (contracts already
 *           hold; the restyle must not break them).
 *   S-P3-3  no-regression (must stay GREEN before and after): S-P1 table
 *           invariant (single ui/table, Provider|Global|Search|Fetch|Test,
 *           7x5, overflow-x-auto scroller, nowrap), S-P2 ranks (P1..P7 never
 *           P100 + Dispatch order tooltip + shrink-0/min-w + px-3 + arrow
 *           boundaries), Carbon Black tokens, NO ProviderMatrix merge,
 *           freesearch-ui ONLY. NOTE: S-P2-5 "no button restyle" covers ONLY
 *           the ArrowUp/ArrowDown arrows â€” this file MUST NOT assert no
 *           Button in file (Green adds ui/Button to the Test cell).
 *
 * P1-FINAL sweep: per-row Test affordance is now an icon button
 * (ui/button ghost icon-sm, aria-label "{name} test connection") that opens
 * the ProviderTestModal (zero fetch on open). The modal Test button runs the
 * existing handleTest (Test/Testing... + exactly one POST). Table is the
 * merged 7-column registry.
 */

const testDir = import.meta.dirname
const settingsSource = readFileSync(path.resolve(testDir, "./SettingsProviders.tsx"), "utf8")
// Slice 4: row/modal/priority siblings own their sources; assertions run
// against the new owners plus the union of the registry feature owners.
const settingsRowSource = readFileSync(
  path.resolve(testDir, "./ProviderRegistryRow.tsx"),
  "utf8"
)
const settingsModalSource = readFileSync(
  path.resolve(testDir, "./ProviderTestModal.tsx"),
  "utf8"
)
const settingsPrioritySource = readFileSync(
  path.resolve(testDir, "./ProviderPriorityControl.tsx"),
  "utf8"
)
const removedButtonShimPath = path.resolve(testDir, "../ui/button.tsx")
const settingsFeatureSource = [
  settingsSource,
  settingsRowSource,
  settingsModalSource,
  settingsPrioritySource,
  readFileSync(path.resolve(testDir, "./ProviderRegistryHeader.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderHealthStatus.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderRowPill.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderOperationControl.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./providerDisplay.ts"), "utf8"),
].join("\n")
const indexCssSource = readFileSync(path.resolve(testDir, "../../index.css"), "utf8")

const norm = (value: string): string => value.toLowerCase().replace(/\s+/g, "")

const SEED_PROVIDER_NAMES = [
  "Brave Search",
  "Keenable",
  "Tavily",
  "Exa",
  "Firecrawl",
  "You.com",
  "Parallel",
  "Tinyfish",
] as const

const EXPECTED_HEADERS = [
  "Provider",
  "Endpoint",
  "Health",
  "Test",
  "Search",
  "Fetch",
  "Global",
] as const
const EXPECTED_RANKS = ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"] as const

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
    return err(404, { detail: "unhandled test route" })
  })
  render(
    <FreeSearchProvider>
      <SettingsView />
    </FreeSearchProvider>
  )
  return stub
}

async function waitForProviders() {
  await waitFor(() => {
    expect(screen.getByText("Brave Search", { exact: true })).toBeInTheDocument()
  })
}

function testButtonFor(provider: string): HTMLElement {
  return screen.getByRole("button", { name: `${provider} test connection` })
}

/** Icon-only affordance: ui/button ghost icon-sm with an svg icon, never bare text. */
function hasIconAffordance(btn: HTMLElement): boolean {
  const dataSlot = btn.getAttribute("data-slot")
  const cls = btn.className ?? ""
  const text = btn.textContent?.trim() ?? ""
  return (
    dataSlot === "button" &&
    text === "" &&
    btn.querySelector("svg") !== null &&
    /rounded/.test(cls)
  )
}

/** Narrow source window around the icon test aria-label (stays inside the row). */
function testCellWindow(): string {
  const marker = "${provider.name} test connection"
  const idx = settingsRowSource.indexOf(marker)
  if (idx < 0) throw new Error("Icon test aria-label marker not found in ProviderRegistryRow.tsx")
  return settingsRowSource.slice(Math.max(0, idx - 600), idx + 600)
}

function findProviderRowTr(provider: string): HTMLTableRowElement {
  const nameEl = screen.getByText(provider, { exact: true })
  const tr = nameEl.closest("tr")
  if (!tr) {
    throw new Error(
      `Provider table row <tr> not found for ${provider} â€” S-P1 table migration missing`
    )
  }
  return tr as HTMLTableRowElement
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

// ---------------------------------------------------------------------------
// S-P3-1: affordance â€” icon test button per row (P1-FINAL)
// ---------------------------------------------------------------------------

describe("S-P3-1: icon test buttons open the ProviderTestModal (affordance)", () => {
  it("every row exposes exactly one icon test button (ui/button, svg, no text)", async () => {
    renderSettings()
    await waitForProviders()
    for (const name of SEED_PROVIDER_NAMES) {
      const btn = testButtonFor(name)
      expect(
        hasIconAffordance(btn),
        `${name} Test must be an icon-only ui/button: ` +
          `data-slot="button" + svg + empty text; ` +
          `got data-slot=${JSON.stringify(btn.getAttribute("data-slot"))} text=${JSON.stringify(btn.textContent)} class=${JSON.stringify(btn.className)}`
      ).toBe(true)
    }
  })

  it("icon test buttons are ghost icon-sm buttons (never the old outline text box)", async () => {
    renderSettings()
    await waitForProviders()
    for (const name of SEED_PROVIDER_NAMES) {
      const btn = testButtonFor(name)
      expect(btn.getAttribute("type")).toBe("button")
      expect(btn).not.toBeDisabled()
      // Icon-only: no visible "Test" text on the row button itself.
      expect(btn.textContent?.trim()).toBe("")
      expect(btn.querySelector("svg")).not.toBeNull()
    }
  })

  it("icon opens the modal with zero fetch (never probes on open)", async () => {
    const user = userEvent.setup()
    const stub = renderSettings()
    await waitForProviders()
    const callsBefore = stub.requests.length
    await user.click(testButtonFor("Brave Search"))
    const dialog = await screen.findByRole("dialog")
    expect(stub.requests.length).toBe(callsBefore)
    expect(stub.requestsTo("/api/v1/providers/brave/test")).toHaveLength(0)
    expect(dialog.textContent).toContain("Brave Search")
  })

  it("Test cell source uses ghost icon-sm Button wired to onOpenTest; modal Test uses handleTest", () => {
    const window_ = testCellWindow()
    expect(window_).toContain("<Button")
    expect(window_).toMatch(/ghost/)
    expect(window_).toMatch(/icon-sm/)
    expect(window_).toMatch(/onOpenTest/)
    expect(settingsModalSource).toContain("@/shared/ui/button")
    // Old ui path was a compat shim over the shared owner (removed in CLEANUP 1.1).
    expect(existsSync(removedButtonShimPath)).toBe(false)
    expect(settingsModalSource).toMatch(/onTest\(provider\.id\)/)
    expect(settingsSource).toContain("handleTest")
  })
})

// ---------------------------------------------------------------------------
// S-P3-2: modal Test states â€” Testing...+disabled, one POST, last-result
// ---------------------------------------------------------------------------

describe("S-P3-2: modal Test interaction states (Test/Testing... + POST)", () => {
  it("modal opens Not tested with a Test button (type=button, enabled)", async () => {
    const user = userEvent.setup()
    renderSettings()
    await waitForProviders()

    await user.click(testButtonFor("Brave Search"))
    const dialog = await screen.findByRole("dialog")
    expect(dialog.textContent).toContain("Not tested")
    const modalTest = within(dialog).getByRole("button", { name: /^Test$/ })
    expect(modalTest.getAttribute("type")).toBe("button")
    expect(modalTest).not.toBeDisabled()
  })

  it("modal Test click flips to Testing... + disabled, then records the last result", async () => {
    const user = userEvent.setup()
    const gate = deferred<Response>()
    renderSettings()
    await waitForProviders()
    testGate = gate.promise

    await user.click(testButtonFor("Brave Search"))
    const dialog = await screen.findByRole("dialog")
    await user.click(within(dialog).getByRole("button", { name: /^Test$/ }))

    await waitFor(() => {
      expect(
        within(screen.getByRole("dialog")).getByRole("button", { name: /testing/i })
      ).toBeInTheDocument()
    })
    const pending = within(screen.getByRole("dialog")).getByRole("button", {
      name: /testing/i,
    })
    expect(pending.textContent?.trim()).toBe("Testing...")
    expect(pending).toBeDisabled()
    expect(pending.getAttribute("type")).toBe("button")

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
    // Last result lands in the modal (status + latency of the probe).
    await waitFor(() => {
      expect(screen.getByRole("dialog").textContent).toMatch(/142ms|healthy/)
    })
  })

  it("emits exactly one POST to /api/v1/providers/brave/test via the modal", async () => {
    const user = userEvent.setup()
    const gate = deferred<Response>()
    const stub = renderSettings()
    await waitForProviders()
    testGate = gate.promise

    await user.click(testButtonFor("Brave Search"))
    const dialog = await screen.findByRole("dialog")
    await user.click(within(dialog).getByRole("button", { name: /^Test$/ }))
    await waitFor(() => {
      expect(
        within(screen.getByRole("dialog")).getByRole("button", { name: /testing/i })
      ).toBeInTheDocument()
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
  })

  it("Test column keeps 7 icon buttons inside the Test cells (label stable)", async () => {
    renderSettings()
    await waitForProviders()
    const table = screen.getByRole("table")
    const headers = Array.from(table.querySelectorAll("thead th")).map(
      (th) => th.textContent?.trim() ?? ""
    )
    const testIdx = headers.indexOf("Test")
    expect(testIdx).toBe(EXPECTED_HEADERS.indexOf("Test"))
    const rows = Array.from(table.querySelectorAll("tbody tr"))
    expect(rows).toHaveLength(8)
    for (const name of SEED_PROVIDER_NAMES) {
      const row = findProviderRowTr(name)
      const cell = row.children[testIdx] as HTMLElement
      const btn = within(cell).getByRole("button", { name: `${name} test connection` })
      expect(btn.getAttribute("type")).toBe("button")
      expect(btn.textContent?.trim()).toBe("")
    }
  })
})

// ---------------------------------------------------------------------------
// S-P3-3: no-regression â€” S-P1 table, S-P2 ranks, tokens, no merge
// ---------------------------------------------------------------------------

describe("S-P3-3: no regression â€” S-P1 table, S-P2 ranks, tokens, merge", () => {
  it("S-P1 table invariant: single merged table, 7 headers, 7x7, scroller, nowrap", async () => {
    renderSettings()
    await waitForProviders()
    expect(screen.getAllByRole("table")).toHaveLength(1)
    const table = screen.getByRole("table")
    expect(
      Array.from(table.querySelectorAll("thead th")).map((th) => th.textContent?.trim() ?? "")
    ).toEqual([...EXPECTED_HEADERS])
    const rows = Array.from(table.querySelectorAll("tbody tr"))
    expect(rows).toHaveLength(8)
    for (const row of rows) {
      expect(row.children).toHaveLength(EXPECTED_HEADERS.length)
    }
    const container = table.closest('[data-slot="table-container"]') as HTMLElement | null
    expect(container, "ui/table scroller must wrap the table").not.toBeNull()
    expect(container!.className).toMatch(/overflow-x-auto/)
    const cells = Array.from(table.querySelectorAll("th, td")) as HTMLElement[]
    expect(cells.length).toBe(EXPECTED_HEADERS.length + 8 * EXPECTED_HEADERS.length)
    for (const cell of cells) {
      expect(cell.className).toMatch(/whitespace-nowrap/)
    }
  })

  it("S-P2 ranks preserved: P1..P7 never P100 with dispatch-order tooltips", async () => {
    renderSettings()
    await waitForProviders()
    for (let rank = 1; rank <= 8; rank += 1) {
      expect(screen.queryAllByText(`P${rank}`, { exact: true })).toHaveLength(1)
      expect(screen.getByText(`P${rank}`, { exact: true }).getAttribute("title")).toBe(
        `Dispatch order ${rank} of 8`
      )
    }
    expect(screen.queryByText("P100", { exact: true })).toBeNull()
    expect(settingsPrioritySource).not.toContain("P{provider.priority}")
    expect(settingsPrioritySource).toContain("Dispatch order")
  })

  it("S-P2 indicator + arrows intact: shrink-0/min-w floor, px-3, lucide up/down with boundaries", async () => {
    renderSettings()
    await waitForProviders()
    // S-P2-5 scope: arrows stay lucide ArrowUp/ArrowDown with exact aria-labels.
    // (Deliberately no "no Button in file" assertion â€” Green adds ui/Button
    // to the Test cell; the restyle guard covers ONLY the arrows.)
    expect(settingsPrioritySource).toContain("lucide-react")
    expect(settingsPrioritySource).toContain("ArrowUp")
    expect(settingsPrioritySource).toContain("ArrowDown")
    for (let rank = 1; rank <= 8; rank += 1) {
      const label = screen.getByText(`P${rank}`, { exact: true })
      const indicator = label.parentElement as HTMLElement | null
      expect(indicator, `P${rank} indicator wrapper must exist`).not.toBeNull()
      expect(indicator!.className).toMatch(/shrink-0/)
      expect(indicator!.className).toMatch(/min-w-/)
    }
    for (const name of SEED_PROVIDER_NAMES) {
      const row = findProviderRowTr(name)
      expect((row.children[0] as HTMLElement).className).toMatch(/px-3/)
      expect(
        screen.getByRole("button", { name: `Move ${name} priority up` })
      ).toBeInTheDocument()
      expect(
        screen.getByRole("button", { name: `Move ${name} priority down` })
      ).toBeInTheDocument()
    }
    expect(
      screen.getByRole("button", { name: "Move Brave Search priority up" })
    ).toBeDisabled()
    expect(
      screen.getByRole("button", { name: "Move Tinyfish priority down" })
    ).toBeDisabled()
    expect(
      screen.getAllByText([...EXPECTED_RANKS][0], { exact: true })
    ).toHaveLength(1)
  })

  it("Carbon Black theme tokens untouched (#1e1e1e scale + #007acc, no oklch)", () => {
    expect(norm(indexCssSource).includes("#1e1e1e")).toBe(true)
    expect(norm(indexCssSource).includes("#252526")).toBe(true)
    expect(norm(indexCssSource).includes("#3e3e42")).toBe(true)
    expect(norm(indexCssSource).includes("#007acc")).toBe(true)
    expect(norm(indexCssSource).includes("oklch(")).toBe(false)
  })

  it("P1-FINAL page merge: fleet telemetry merged into SettingsProviders (ProviderMatrix retired)", () => {
    for (const marker of ["Endpoint", "Health", "Quota", "p95", "ProviderTestModal"]) {
      expect(settingsFeatureSource, `merged registry must carry ${marker}`).toContain(marker)
    }
  })

  it("freesearch-ui ONLY: SettingsProviders imports no backend/python paths", () => {
    expect(settingsFeatureSource).not.toMatch(/\.py["']/)
    expect(settingsFeatureSource).not.toMatch(/src\/freesearch/)
  })
})
})

describe("SettingsProviders.s-p4.test.tsx", () => {

/**
 * S-P4 Providers wasted space — BDD Acceptance (RED phase).
 *
 * User bullet (verbatim): "Wasted space". Read-only:
 * .agents/FEEDBACK/UI/feedback.md L24. SEE image yourself:
 * .agents/FEEDBACK/UI/image-4.png (registry hugs left ~50%, right void).
 *
 * BUG image-4.png shows the Provider registry table hugging the left ~50%
 * of the Settings main column with an empty void on the right — the
 * section is capped at max-w-4xl so it never fills the available width at
 * desktop viewports.
 *
 * Plan under test (ONLY SettingsProviders.tsx, freesearch-ui/ ONLY):
 *   L62 section (max-w-4xl -> w-full max-w-none) +
 *   L70 frame (+w-full max-w-none, KEEP overflow-hidden). No other changes.
 *
 * AC mapping:
 *   S-P4-1  available-width section — <section> carries w-full + max-w-none
 *           and NO capped max-w (no max-w-4xl/3xl/5xl, no other max-w-*
 *           except max-w-none). Source + rendered DOM token assertions.
 *           RED: current L62 is `space-y-4 max-w-4xl` (no w-full, no
 *           max-w-none, capped) so every S-P4-1 assertion FAILS cleanly.
 *   S-P4-2  available-width frame — L70 frame div gains w-full + max-w-none
 *           while KEEPING overflow-hidden (+ rounded-lg + border). Source +
 *           rendered DOM token assertions. RED: current frame is
 *           `overflow-hidden rounded-lg border ...` with no w-full/max-w-none,
 *           so the w-full/max-w-none assertions FAIL cleanly while the
 *           KEEP-overflow-hidden assertions PASS (the keep-guard).
 *   S-P4-3  1440px fills main — at window.innerWidth 1440 the rendered
 *           section + frame still carry w-full max-w-none with no cap, the
 *           single 7-row table with min-w-[880px] is present inside the
 *           w-full scroller. jsdom has no layout engine so the executable
 *           proxy is the width-class invariant at the 1440px viewport (same
 *           structural-invariant approach as S-P1-2/S-P2-3); pixel proof
 *           needs a browser (Playwright). RED: fails on the missing
 *           w-full/max-w-none tokens, exactly like S-P4-1/S-P4-2.
 *   S-P4-4  responsive-scroll preserved (GREEN in Red phase) — the SAME
 *           ui/table table-container scroller (data-slot + overflow-x-auto +
 *           w-full) wraps the table, Table keeps min-w-[880px], all th/td
 *           keep whitespace-nowrap, and the 375px viewport keeps the nowrap
 *           cells inside the horizontal scroller with no flex-wrap. These
 *           MUST pass before and after (the plan adds width, never removes
 *           the scroller).
 *   S-P4-5  regression guards (must stay GREEN before and after):
 *           S-P1 table invariant (single ui/table, exact headers, 7x5,
 *           scroller, nowrap), S-P2 ranks (P1..P7 never P100 + Dispatch
 *           order tooltip + shrink-0/min-w + px-3 + arrow boundaries),
 *           S-P3 Test affordance (ui/button outline sm box, states, one
 *           POST), SettingsView pills (Providers/Keys/Failover pill
 *           variant), Carbon Black tokens, NO ProviderMatrix merge,
 *           sibling sections follow suit (KeyVault full width per K1, Failover per F1),
 *           freesearch-ui ONLY (no backend/python imports).
 *
 * RED expectation:
 *   S-P4-1 FAILS cleanly (section capped max-w-4xl, no w-full/max-w-none).
 *   S-P4-2 FAILS cleanly on w-full/max-w-none (overflow-hidden keep PASSES).
 *   S-P4-3 FAILS cleanly (width tokens missing at 1440px).
 *   S-P4-4 + S-P4-5 PASS (scroller + prior bullets intact).
 */

const testDir = import.meta.dirname
const settingsSource = readFileSync(path.resolve(testDir, "./SettingsProviders.tsx"), "utf8")
// Slice 4: row/modal/priority siblings own their sources; assertions run
// against the new owners plus the union of the registry feature owners.
const settingsPrioritySource = readFileSync(
  path.resolve(testDir, "./ProviderPriorityControl.tsx"),
  "utf8"
)
const settingsModalSource = readFileSync(
  path.resolve(testDir, "./ProviderTestModal.tsx"),
  "utf8"
)
const removedButtonShimPath = path.resolve(testDir, "../ui/button.tsx")
const settingsFeatureSource = [
  settingsSource,
  settingsPrioritySource,
  settingsModalSource,
  readFileSync(path.resolve(testDir, "./ProviderRegistryRow.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderRegistryHeader.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderHealthStatus.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderRowPill.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderOperationControl.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./providerDisplay.ts"), "utf8"),
].join("\n")
const indexCssSource = readFileSync(path.resolve(testDir, "../../index.css"), "utf8")
// P1-FINAL (blessed inversion): ProviderMatrix.tsx is DELETED by the merge —
// no test may read it (the file is gone Green).
const keyVaultSource = readFileSync(path.resolve(testDir, "./SettingsKeyVault.tsx"), "utf8")
const failoverSource = readFileSync(path.resolve(testDir, "./SettingsFailover.tsx"), "utf8")

const norm = (value: string): string => value.toLowerCase().replace(/\s+/g, "")

const SEED_PROVIDER_NAMES = [
  "Brave Search",
  "Keenable",
  "Tavily",
  "Exa",
  "Firecrawl",
  "You.com",
  "Parallel",
  "Tinyfish",
] as const

const EXPECTED_HEADERS = [
  "Provider",
  "Endpoint",
  "Health",
  "Test",
  "Search",
  "Fetch",
  "Global",
] as const
const EXPECTED_RANKS = ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"] as const

const ORIGINAL_INNER_WIDTH = window.innerWidth

function renderSettings(): FetchStub {
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
      return ok({
        provider: "brave",
        ok: true,
        status: "healthy",
        latency_ms: 142,
        checked_at: "2026-09-06T10:04:00Z",
        detail: null,
      })
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

async function waitForProviders() {
  await waitFor(() => {
    expect(screen.getByText("Brave Search", { exact: true })).toBeInTheDocument()
  })
}

/** Exact class-token list for an element (Tailwind tokens are whitespace-separated). */
function classTokens(el: Element): string[] {
  return (el.getAttribute("class") ?? "").split(/\s+/).filter(Boolean)
}

/** L62 <section className="..."> token list from source. */
function sectionClassFromSource(): string[] {
  const match = settingsSource.match(/<section\s+className="([^"]*)"/)
  if (!match) throw new Error("<section className> not found in SettingsProviders.tsx (L62 moved?)")
  return match[1].split(/\s+/).filter(Boolean)
}

/** L70 frame <div className="...overflow-hidden..."> token list from source. */
function frameClassFromSource(): string[] {
  const match = settingsSource.match(/<div\s+className="([^"]*overflow-hidden[^"]*)"/)
  if (!match) {
    throw new Error(
      "Frame <div> with overflow-hidden not found in SettingsProviders.tsx (L70 moved?)"
    )
  }
  return match[1].split(/\s+/).filter(Boolean)
}

function providerSection(): HTMLElement {
  const table = screen.getByRole("table")
  const section = table.closest("section")
  if (!section) throw new Error("Provider registry <section> not found around the table")
  return section as HTMLElement
}

function providerFrame(): HTMLElement {
  const table = screen.getByRole("table")
  const container = table.closest('[data-slot="table-container"]')
  if (!container) throw new Error("ui/table container [data-slot=table-container] must wrap the table")
  const frame = container.parentElement
  if (!frame) throw new Error("Frame <div> (table-container parent) not found")
  return frame as HTMLElement
}

function findProviderRowTr(provider: string): HTMLTableRowElement {
  const nameEl = screen.getByText(provider, { exact: true })
  const tr = nameEl.closest("tr")
  if (!tr) {
    throw new Error(
      `Provider table row <tr> not found for ${provider} — S-P1 table migration missing`
    )
  }
  return tr as HTMLTableRowElement
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  ;(window.innerWidth as number) = ORIGINAL_INNER_WIDTH
  window.dispatchEvent(new Event("resize"))
})

// ---------------------------------------------------------------------------
// S-P4-1: section spans the available width (RED)
// ---------------------------------------------------------------------------

describe("S-P4-1: registry section spans available width (w-full max-w-none, no cap)", () => {
  it("section source carries w-full", () => {
    expect(
      sectionClassFromSource(),
      `L62 section must carry w-full; got ${JSON.stringify(sectionClassFromSource())}`
    ).toContain("w-full")
  })

  it("section source carries max-w-none", () => {
    expect(
      sectionClassFromSource(),
      `L62 section must carry max-w-none; got ${JSON.stringify(sectionClassFromSource())}`
    ).toContain("max-w-none")
  })

  it("section source has no capped max-w (no max-w-4xl/3xl/5xl, no other max-w-* but max-w-none)", () => {
    const tokens = sectionClassFromSource()
    expect(tokens, "L62 section must not keep max-w-4xl").not.toContain("max-w-4xl")
    expect(tokens, "section must not be capped at max-w-3xl").not.toContain("max-w-3xl")
    expect(tokens, "section must not be capped at max-w-5xl").not.toContain("max-w-5xl")
    const capped = tokens.filter((t) => /^max-w-/.test(t) && t !== "max-w-none")
    expect(capped, `section must have no capped max-w-*, got ${JSON.stringify(tokens)}`).toEqual([])
  })

  it("rendered section carries w-full + max-w-none with no capped max-w", async () => {
    renderSettings()
    await waitForProviders()
    const tokens = classTokens(providerSection())
    expect(tokens, `rendered section must carry w-full; got ${JSON.stringify(tokens)}`).toContain(
      "w-full"
    )
    expect(
      tokens,
      `rendered section must carry max-w-none; got ${JSON.stringify(tokens)}`
    ).toContain("max-w-none")
    const capped = tokens.filter((t) => /^max-w-/.test(t) && t !== "max-w-none")
    expect(capped, `rendered section must have no capped max-w-*; got ${JSON.stringify(tokens)}`).toEqual(
      []
    )
  })
})

// ---------------------------------------------------------------------------
// S-P4-2: frame spans available width, keeps overflow-hidden (RED on width)
// ---------------------------------------------------------------------------

describe("S-P4-2: table frame spans available width and keeps overflow-hidden", () => {
  it("frame source carries w-full", () => {
    expect(
      frameClassFromSource(),
      `L70 frame must carry w-full; got ${JSON.stringify(frameClassFromSource())}`
    ).toContain("w-full")
  })

  it("frame source carries max-w-none", () => {
    expect(
      frameClassFromSource(),
      `L70 frame must carry max-w-none; got ${JSON.stringify(frameClassFromSource())}`
    ).toContain("max-w-none")
  })

  it("frame source KEEPS overflow-hidden (responsive scroll contract)", () => {
    expect(
      frameClassFromSource(),
      `L70 frame must KEEP overflow-hidden; got ${JSON.stringify(frameClassFromSource())}`
    ).toContain("overflow-hidden")
  })

  it("frame source keeps the rounded bordered card (rounded-lg + border)", () => {
    const tokens = frameClassFromSource()
    expect(tokens, `frame must keep rounded-lg; got ${JSON.stringify(tokens)}`).toContain(
      "rounded-lg"
    )
    expect(tokens.some((t) => t === "border" || t.startsWith("border-"))).toBe(true)
  })

  it("rendered frame carries w-full + max-w-none and keeps overflow-hidden", async () => {
    renderSettings()
    await waitForProviders()
    const tokens = classTokens(providerFrame())
    expect(tokens, `rendered frame must carry w-full; got ${JSON.stringify(tokens)}`).toContain(
      "w-full"
    )
    expect(
      tokens,
      `rendered frame must carry max-w-none; got ${JSON.stringify(tokens)}`
    ).toContain("max-w-none")
    expect(
      tokens,
      `rendered frame must KEEP overflow-hidden; got ${JSON.stringify(tokens)}`
    ).toContain("overflow-hidden")
  })
})

// ---------------------------------------------------------------------------
// S-P4-3: 1440px viewport fills the main column (RED on width)
// ---------------------------------------------------------------------------

describe("S-P4-3: 1440px viewport fills the Settings main column", () => {
  it("at 1440px the section + frame still carry w-full max-w-none with no cap", async () => {
    ;(window.innerWidth as number) = 1440
    window.dispatchEvent(new Event("resize"))
    renderSettings()
    await waitForProviders()
    const sectionTokens = classTokens(providerSection())
    const frameTokens = classTokens(providerFrame())
    expect(
      sectionTokens,
      `1440px section must carry w-full; got ${JSON.stringify(sectionTokens)}`
    ).toContain("w-full")
    expect(
      sectionTokens,
      `1440px section must carry max-w-none; got ${JSON.stringify(sectionTokens)}`
    ).toContain("max-w-none")
    expect(
      sectionTokens.filter((t) => /^max-w-/.test(t) && t !== "max-w-none"),
      `1440px section must have no capped max-w-*; got ${JSON.stringify(sectionTokens)}`
    ).toEqual([])
    expect(frameTokens, `1440px frame must carry w-full; got ${JSON.stringify(frameTokens)}`).toContain(
      "w-full"
    )
    expect(
      frameTokens,
      `1440px frame must carry max-w-none; got ${JSON.stringify(frameTokens)}`
    ).toContain("max-w-none")
  })

  it("at 1440px the single 7-row merged table with min-w-[960px] sits inside the w-full scroller", async () => {
    ;(window.innerWidth as number) = 1440
    window.dispatchEvent(new Event("resize"))
    renderSettings()
    await waitForProviders()
    expect(screen.getAllByRole("table")).toHaveLength(1)
    const table = screen.getByRole("table")
    expect(table.querySelectorAll("tbody tr")).toHaveLength(8)
    expect(table.className).toMatch(/min-w-\[960px\]/)
    const container = table.closest('[data-slot="table-container"]') as HTMLElement | null
    expect(container, "ui/table scroller must wrap the table at 1440px").not.toBeNull()
    expect(container!.className).toMatch(/w-full/)
    expect(container!.className).toMatch(/overflow-x-auto/)
  })
})

// ---------------------------------------------------------------------------
// S-P4-4: responsive scroll preserved (GREEN in Red phase)
// ---------------------------------------------------------------------------

describe("S-P4-4: responsive horizontal scroll preserved (no wrap, 375px scrolls)", () => {
  it("table container is the same ui/table scroller (data-slot + overflow-x-auto + w-full)", async () => {
    renderSettings()
    await waitForProviders()
    const table = screen.getByRole("table")
    const container = table.closest('[data-slot="table-container"]') as HTMLElement | null
    expect(container, "ui/table container [data-slot=table-container] must wrap the table").not.toBeNull()
    expect(container!.className).toMatch(/overflow-x-auto/)
    expect(container!.className).toMatch(/w-full/)
    expect(table.className).toMatch(/w-full/)
  })

  it("Table keeps min-w-[960px] in source and in the DOM", async () => {
    expect(settingsSource).toMatch(/min-w-\[960px\]/)
    renderSettings()
    await waitForProviders()
    expect(screen.getByRole("table").className).toMatch(/min-w-\[960px\]/)
  })

  it("all header and body cells keep whitespace-nowrap (no wrapping)", async () => {
    renderSettings()
    await waitForProviders()
    const table = screen.getByRole("table")
    const cells = Array.from(table.querySelectorAll("th, td")) as HTMLElement[]
    expect(cells.length).toBe(EXPECTED_HEADERS.length + 8 * EXPECTED_HEADERS.length)
    for (const cell of cells) {
      expect(cell.className).toMatch(/whitespace-nowrap/)
    }
  })

  it("375px viewport keeps nowrap cells inside the horizontal scroller", async () => {
    ;(window.innerWidth as number) = 375
    window.dispatchEvent(new Event("resize"))
    renderSettings()
    await waitForProviders()
    const table = screen.getByRole("table")
    const container = table.closest('[data-slot="table-container"]') as HTMLElement
    expect(container.className).toMatch(/overflow-x-auto/)
    expect(table.className).toMatch(/min-w-\[960px\]/)
    const cells = Array.from(table.querySelectorAll("th, td")) as HTMLElement[]
    expect(cells.length).toBe(EXPECTED_HEADERS.length + 8 * EXPECTED_HEADERS.length)
    for (const cell of cells) {
      expect(cell.className).toMatch(/whitespace-nowrap/)
    }
    expect(settingsFeatureSource.includes("flex-wrap")).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// S-P4-5: regression guards — S-P1/S-P2/S-P3 + SettingsView stay Green
// ---------------------------------------------------------------------------

describe("S-P4-5: no regression — S-P1 table, S-P2 ranks, S-P3 buttons, SettingsView", () => {
  it("S-P1 table invariant: single merged table, 7 headers, 7x7, scroller, nowrap", async () => {
    renderSettings()
    await waitForProviders()
    expect(screen.getAllByRole("table")).toHaveLength(1)
    const table = screen.getByRole("table")
    expect(
      Array.from(table.querySelectorAll("thead th")).map((th) => th.textContent?.trim() ?? "")
    ).toEqual([...EXPECTED_HEADERS])
    const rows = Array.from(table.querySelectorAll("tbody tr"))
    expect(rows).toHaveLength(8)
    for (const row of rows) {
      expect(row.children).toHaveLength(EXPECTED_HEADERS.length)
    }
    const container = table.closest('[data-slot="table-container"]') as HTMLElement | null
    expect(container, "ui/table scroller must wrap the table").not.toBeNull()
    expect(container!.className).toMatch(/overflow-x-auto/)
    const cells = Array.from(table.querySelectorAll("th, td")) as HTMLElement[]
    expect(cells.length).toBe(EXPECTED_HEADERS.length + 8 * EXPECTED_HEADERS.length)
    for (const cell of cells) {
      expect(cell.className).toMatch(/whitespace-nowrap/)
    }
  })

  it("S-P2 ranks preserved: P1..P7 never P100 with dispatch-order tooltips", async () => {
    renderSettings()
    await waitForProviders()
    for (let rank = 1; rank <= 8; rank += 1) {
      expect(screen.queryAllByText(`P${rank}`, { exact: true })).toHaveLength(1)
      expect(screen.getByText(`P${rank}`, { exact: true }).getAttribute("title")).toBe(
        `Dispatch order ${rank} of 8`
      )
    }
    expect(screen.queryByText("P100", { exact: true })).toBeNull()
    expect(settingsPrioritySource).not.toContain("P{provider.priority}")
    expect(settingsPrioritySource).toContain("Dispatch order")
  })

  it("S-P2 indicator + arrows intact: shrink-0/min-w floor, px-3, lucide up/down with boundaries", async () => {
    renderSettings()
    await waitForProviders()
    expect(settingsPrioritySource).toContain("lucide-react")
    expect(settingsPrioritySource).toContain("ArrowUp")
    expect(settingsPrioritySource).toContain("ArrowDown")
    for (let rank = 1; rank <= 8; rank += 1) {
      const label = screen.getByText(`P${rank}`, { exact: true })
      const indicator = label.parentElement as HTMLElement | null
      expect(indicator, `P${rank} indicator wrapper must exist`).not.toBeNull()
      expect(indicator!.className).toMatch(/shrink-0/)
      expect(indicator!.className).toMatch(/min-w-/)
    }
    for (const name of SEED_PROVIDER_NAMES) {
      const row = findProviderRowTr(name)
      expect((row.children[0] as HTMLElement).className).toMatch(/px-3/)
      expect(
        screen.getByRole("button", { name: `Move ${name} priority up` })
      ).toBeInTheDocument()
      expect(
        screen.getByRole("button", { name: `Move ${name} priority down` })
      ).toBeInTheDocument()
    }
    expect(
      screen.getByRole("button", { name: "Move Brave Search priority up" })
    ).toBeDisabled()
    expect(
      screen.getByRole("button", { name: "Move Tinyfish priority down" })
    ).toBeDisabled()
    expect(screen.getAllByText([...EXPECTED_RANKS][0], { exact: true })).toHaveLength(1)
  })

  it("S-P3 Test affordance: icon buttons per row open the modal (ghost icon-sm, exact labels)", async () => {
    renderSettings()
    await waitForProviders()
    for (const name of SEED_PROVIDER_NAMES) {
      const btn = screen.getByRole("button", { name: `${name} test connection` })
      expect(btn.getAttribute("data-slot")).toBe("button")
      expect(btn.getAttribute("type")).toBe("button")
      expect(btn.getAttribute("aria-label")).toBe(`${name} test connection`)
      expect(btn.textContent?.trim()).toBe("")
      expect(btn.querySelector("svg")).not.toBeNull()
    }
    expect(settingsModalSource).toContain("@/shared/ui/button")
    // Old ui path was a compat shim over the shared owner (removed in CLEANUP 1.1).
    expect(existsSync(removedButtonShimPath)).toBe(false)
  })

  it("SettingsView pills stay Providers/Keys/Failover on the pill variant", async () => {
    renderSettings()
    await waitForProviders()
    expect(screen.getAllByRole("tab")).toHaveLength(3)
    for (const label of ["Providers", "Keys", "Failover"]) {
      expect(screen.getByRole("tab", { name: new RegExp(`^${label}$`) })).toBeInTheDocument()
    }
    const pillList = document.querySelector('[data-slot="tabs-list"][data-variant="pill"]')
    expect(pillList, "pill tablist must exist").not.toBeNull()
    expect(
      within(pillList as HTMLElement)
        .getAllByRole("tab")
        .map((t) => t.textContent)
    ).toEqual(["Providers", "Keys", "Failover"])
    expect(
      document.querySelectorAll('[data-slot="tabs-list"][data-variant="line"]')
    ).toHaveLength(0)
  })

  it("Carbon Black theme tokens untouched (#1e1e1e scale + #007acc, no oklch)", () => {
    expect(norm(indexCssSource).includes("#1e1e1e")).toBe(true)
    expect(norm(indexCssSource).includes("#252526")).toBe(true)
    expect(norm(indexCssSource).includes("#3e3e42")).toBe(true)
    expect(norm(indexCssSource).includes("#007acc")).toBe(true)
    expect(norm(indexCssSource).includes("oklch(")).toBe(false)
  })

  it("scope: Keys spans full width (K1) and Failover spans full width (F1)", () => {
    expect(keyVaultSource).not.toMatch(/max-w-4xl/)
    expect(keyVaultSource).toMatch(/w-full/)
    expect(keyVaultSource).toMatch(/max-w-none/)
    expect(failoverSource).not.toMatch(/max-w-3xl/)
    expect(failoverSource).toMatch(/w-full/)
    expect(failoverSource).toMatch(/max-w-none/)
  })

  it("P1-FINAL page merge: fleet telemetry merged into SettingsProviders (ProviderMatrix retired)", () => {
    for (const marker of ["Endpoint", "Health", "Quota", "p95", "ProviderTestModal"]) {
      expect(settingsFeatureSource, `merged registry must carry ${marker}`).toContain(marker)
    }
  })

  it("freesearch-ui ONLY: SettingsProviders imports no backend/python paths", () => {
    expect(settingsFeatureSource).not.toMatch(/\.py["']/)
    expect(settingsFeatureSource).not.toMatch(/src\/freesearch/)
  })
})
})
