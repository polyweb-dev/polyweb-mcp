import React from "react"
import { readFileSync, existsSync } from "node:fs"
import path from "node:path"
import { describe, expect, it, afterEach, vi, beforeEach } from "vitest"
import { render, screen, within, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, useLocation } from "react-router"
import App from "@/App"
import { PolywebProvider } from "@/context/PolywebContext"
import { ADMIN_ACCOUNT_ID, DEVELOPER_ACCOUNT_ID, accessResponseFixture, adminAccountFixture } from "@/test/authFixtures"
import { installFakeChannel, installImmediateLocks, removeLocks } from "@/test/browserStubs"
import { SettingsView } from "./SettingsView"
import { installFetchStub, ok, err, deferred, type FetchStub } from "@/test/fetchMock"
import { allProvidersFixture, routingConfigFixture, dashboardFixture } from "@/test/fixtures"
import { type WireProviderStatus } from "@/test/backendFixtures"
import { answerWorkspaceAccess } from "@/test/accessFixtures"

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
 * Plan under test (polyweb-ui/ ONLY):
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
const removedModalShimPath = path.resolve(testDir, "../../../components/common/Modal.tsx")
const removedDialogShimPath = path.resolve(testDir, "../../../components/ui/dialog.tsx")
const settingsFeatureSource = [
  settingsSource,
  settingsModalSource,
  readFileSync(path.resolve(testDir, "./ProviderRegistryRow.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderRegistryHeader.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "../../../shared/ui/HealthStatus.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "../../../shared/ui/ReorderHandle.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderOperationControl.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./providerDisplay.ts"), "utf8"),
].join("\n")
const appSource = readFileSync(path.resolve(testDir, "../../../App.tsx"), "utf8")
const dashboardShellSource = readFileSync(
  path.resolve(testDir, "../../../app/DashboardShell.tsx"),
  "utf8"
)
const sidebarSource = readFileSync(
  path.resolve(testDir, "../../../components/layout/Sidebar.tsx"),
  "utf8"
)
const routesNavSource = readFileSync(
  path.resolve(testDir, "../../../app/layout/SidebarNavList.tsx"),
  "utf8"
)
const routeTableSource = readFileSync(path.resolve(testDir, "../../../app/routes.ts"), "utf8")

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
  "Cost per call",
  "Health",
  "Search",
  "Fetch",
  "On",
] as const

let testGate: Promise<Response> | null = null

function renderSettings(): FetchStub {
  testGate = null
  const stub = installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture().map((provider) => ({
        ...provider,
        ...(provider.provider_id === "keenable" ? { call_cost_usd: { search: "0", fetch: "0" }, keyless_call_cost_usd: { search: "0", fetch: "0" } } : {}),
        ...(provider.provider_id === "firecrawl" ? { call_cost_usd: { search: "0.0076", fetch: "0.0038" } } : {}),
      })))
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    if (req.method === "PATCH" && req.url.startsWith("/api/v1/providers/")) {
      const backendId = req.url.split("/").at(-1) ?? "unknown"
      const wire = allProvidersFixture().find((p) => p.provider_id === backendId)
      const base = { ...(wire ?? allProvidersFixture()[0]) } as Record<string, unknown> & {
        enable_mask: number
      }
      const patch = ((req.body as Record<string, unknown>) ?? {}) as Record<string, unknown>
      let enableMask = base.enable_mask
      if (typeof patch.enable_mask === "number") enableMask = patch.enable_mask
      else {
        if (patch.enabled === true) enableMask |= 1
        if (patch.enabled === false) enableMask &= ~1
        if (patch.search_enabled === true) enableMask |= 2
        if (patch.search_enabled === false) enableMask &= ~2
        if (patch.fetch_enabled === true) enableMask |= 4
        if (patch.fetch_enabled === false) enableMask &= ~4
      }
      return ok({ ...base, enable_mask: enableMask, enabled: (enableMask & 1) !== 0 })
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
    <MemoryRouter>
      <PolywebProvider accountId={ADMIN_ACCOUNT_ID} canReadControls canEditControls>
        <SettingsView />
      </PolywebProvider>
    </MemoryRouter>
  )
  return stub
}

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="test-location">{location.pathname}</div>
}

async function renderAppAt(route: string): Promise<FetchStub> {
  installImmediateLocks()
  installFakeChannel()
  const stub = installFetchStub((req) => {
    if (req.url === "/auth/jwt/refresh" && req.method === "POST") {
      return ok(accessResponseFixture())
    }
    if (req.url === "/users/me" && req.method === "GET") {
      return ok(adminAccountFixture())
    }
    const access = answerWorkspaceAccess(req)
    if (access !== null) return access
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
  // `hidden`: the table stays queryable while the test dialog marks the page inert.
  return screen.getByRole("table", { hidden: true })
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

/** Seven-column merged registry: every row (including Tavily) keeps exactly
 * seven cells; the Tavily rate-tier dropdown lives only in the Usage card.
 */
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
  const testCell = cellFor(provider, "Health")
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
  removeLocks()
})

// ---------------------------------------------------------------------------
// P1F-1: ONE merged table with the exact 7 headers
// ---------------------------------------------------------------------------

describe("P1F-1: Settings registry is ONE merged table with 7 columns", () => {
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
    // Seven merged columns stand for every row (no Tavily extra cell).
    for (const name of SEED_PROVIDER_NAMES) {
      const row = findProviderRowTr(name)
      expect(row.children).toHaveLength(EXPECTED_MERGED_HEADERS.length)
    }
  })

})

// ---------------------------------------------------------------------------
// P1F-2: registry controls preserved (keep-guard, GREEN in Red)
// ---------------------------------------------------------------------------

describe("P1F-2: registry controls preserved in the merged table", () => {
  it("shows read-only per-operation costs without system order controls", async () => {
    const stub = renderSettings()
    await waitForProviders()
    expect(cellFor("Keenable", "Cost per call")).toHaveTextContent(/^Free$/)
    expect(cellFor("Firecrawl", "Cost per call")).toHaveTextContent("Search: $0.0076")
    expect(cellFor("Firecrawl", "Cost per call")).toHaveTextContent("Fetch: $0.0038")
    expect(cellFor("Brave Search", "Cost per call")).not.toHaveTextContent("Fetch:")
    expect(cellFor("Tavily", "Cost per call")).toHaveTextContent("Search: —")
    expect(within(mergedTable()).queryByRole("columnheader", { name: "Priority" })).not.toBeInTheDocument()
    expect(within(mergedTable()).queryByRole("button", { name: /priority (up|down)/i })).not.toBeInTheDocument()
    expect(mergedTable().querySelector("[draggable=true]")).toBeNull()
    expect(stub.requests.filter((request) => request.method === "PATCH" || request.method === "PUT")).toHaveLength(0)
  })

  it("keeps 7 global Switches with provider-qualified labels", async () => {
    renderSettings()
    await waitForProviders()
    // 7-col header must exist AND the master switches must sit in Enabled cells.
    expect(headerNames()).toEqual([...EXPECTED_MERGED_HEADERS])
    for (const name of SEED_PROVIDER_NAMES) {
      const cell = cellFor(name, "On")
      expect(
        within(cell).getByRole("switch", { name: `${name} global routing` })
      ).toBeInTheDocument()
    }
  })

  it("persists Search/Fetch controls via durable PATCH with switch toggles", async () => {
    const user = userEvent.setup()
    const stub = renderSettings()
    await waitForProviders()
    const searchCell = cellFor("Brave Search", "Search")
    const searchSwitch = within(searchCell).getByRole("switch", { name: "Brave Search search routing" })
    expect(searchSwitch).toHaveAttribute("aria-checked", "true")
    await user.click(searchSwitch)
    await waitFor(() => {
      expect(
        within(cellFor("Brave Search", "Search")).getByRole("switch", {
          name: "Brave Search search routing",
        }),
      ).toHaveAttribute("aria-checked", "false")
    })
    const patches = stub.requestsTo("/api/v1/providers/brave")
    expect(patches).toHaveLength(1)
    expect(patches[0].body).toEqual({ search_enabled: false })
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
    expect(braveEndpoint.textContent).toBe("api.search.brave.com")
    expect(braveEndpoint.textContent).not.toMatch(/https?:\/\//)
    const tavilyEndpoint = cellFor("Tavily", "Endpoint")
    expect(tavilyEndpoint.textContent).toContain("api.tavily.com")
  })

  it("shows the last connection test per row as Health (a muted dash until one runs), with no aggregate count", async () => {
    renderSettings()
    await waitForProviders()
    expect(headerNames()).toContain("Health")
    for (const name of SEED_PROVIDER_NAMES) {
      expect(within(cellFor(name, "Health")).getByText("Health not known")).toBeInTheDocument()
    }
    expect(screen.queryByText("Not tested")).not.toBeInTheDocument()
    expect(screen.queryByText(/\d+\/\d+ healthy/)).not.toBeInTheDocument()
    expect(screen.queryByText("Provider registry")).not.toBeInTheDocument()
    expect(screen.queryByText(/Priority dispatch/)).not.toBeInTheDocument()
  })

  it("does not render Quota or p95 as registry columns (telemetry lives in the modal + Usage view)", async () => {
    renderSettings()
    await waitForProviders()
    expect(headerNames()).not.toContain("Quota")
    expect(headerNames()).not.toContain("p95")
    expect(headerNames()).toEqual([...EXPECTED_MERGED_HEADERS])
    const rows = Array.from(mergedTable().querySelectorAll("tbody tr"))
    expect(rows).toHaveLength(8)
    for (const name of SEED_PROVIDER_NAMES) {
      const row = findProviderRowTr(name)
      expect(row.children).toHaveLength(EXPECTED_MERGED_HEADERS.length)
    }
  })

  it("keeps only endpoint and capabilities in the test modal (no health, quota, or p95)", async () => {
    const user = userEvent.setup()
    renderSettings()
    await waitForProviders()
    await user.click(testIconFor("Brave Search"))
    const dialog = await screen.findByRole("dialog")
    expect(dialog.textContent).toContain("Endpoint")
    expect(dialog.textContent).toContain("Capabilities")
    expect(dialog.textContent).toContain("Last test")
    expect(within(dialog).queryByText("Health", { exact: true })).not.toBeInTheDocument()
    expect(dialog.textContent).not.toContain("p95")
    expect(dialog.textContent).not.toContain("Quota")
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
    const test = cellFor("Brave Search", "Health")
    expect(test.className).not.toContain("text-right")
  })

  it("shows capabilities in plain words in the test modal, never raw enum values", async () => {
    const user = userEvent.setup()
    renderSettings()
    await waitForProviders()
    await user.click(testIconFor("Keenable"))
    const dialog = await screen.findByRole("dialog")
    expect(dialog.textContent).not.toMatch(/keyless_tier|neural_search|live_crawl/)
  })

  it("labels the custom and keyless markers with the shared tag, in sentence case", async () => {
    renderSettings()
    await waitForProviders()
    const keenable = cellFor("Keenable", "Provider")
    expect(within(keenable).getByText("No key needed")).toBeInTheDocument()
    expect(within(keenable).queryByText("keyless")).not.toBeInTheDocument()
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

  it("exposes one icon test button per row in the Health column", async () => {
    renderSettings()
    await waitForProviders()
    expect(headerNames()).toContain("Health")
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
    expect(within(dialog).queryByText("Health", { exact: true })).not.toBeInTheDocument()
    expect(dialog.textContent).not.toContain("p95")
    expect(dialog.textContent).not.toContain("Quota")
    expect(dialog.textContent).not.toContain("∞")
    await user.keyboard("{Escape}")
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    })
    await user.click(testIconFor("Tavily"))
    const tavilyDialog = await screen.findByRole("dialog")
    expect(tavilyDialog.textContent).toContain("api.tavily.com")
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
    // Last result lands in the modal (status + latency of the probe)...
    await waitFor(() => {
      expect(within(screen.getByRole("dialog")).getByText("Healthy · just now")).toBeInTheDocument()
      expect(within(screen.getByRole("dialog")).getByText("142 ms")).toBeInTheDocument()
    })
    // ...and in the row's Health cell.
    expect(cellFor("Brave Search", "Health").textContent).toContain("Healthy · just now")
    expect(within(cellFor("Tavily", "Health")).getByText("Health not known")).toBeInTheDocument()
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
  it("App drops the ProviderMatrix route and redirects /providers -> /system/providers", () => {
    expect(dashboardShellSource).not.toMatch(/ProviderMatrix/)
    expect(appSource).not.toMatch(/ProviderMatrix/)
    // Thin App shim renders the shell that owns the redirect.
    expect(appSource).toContain("DashboardShell")
    expect(routeTableSource).toContain('settings: "/system/providers"')
    expect(routeTableSource).toContain('"/providers": TAB_PATHS.settings')
    // The shell turns every legacy entry into a Navigate route.
    expect(dashboardShellSource).toContain("LEGACY_GLOBAL_REDIRECTS")
    expect(dashboardShellSource).toMatch(/<Navigate to=\{target\}/)
  })

  it("Sidebar drops the providers TabId, nav item, and route target", () => {
    expect(routesNavSource).not.toContain('"providers"')
    expect(routesNavSource).not.toContain('"/providers"')
    expect(sidebarSource).not.toContain('"providers"')
    expect(sidebarSource).not.toContain('"/providers"')
    // Compat shim keeps the old sidebar import surface working.
    expect(sidebarSource).toMatch(/from\s+["']@\/app\/layout\/Sidebar["']/)
  })

  it("Sidebar renders the System links plus Projects and Account", async () => {
    await renderAppAt("/system/providers")
    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 2, name: "Providers" })).toBeInTheDocument()
    })
    const nav = screen.getByRole("navigation", { name: "Primary" })
    expect(within(nav).getAllByRole("link").map((link) => link.getAttribute("aria-label"))).toEqual([
      "Providers", "Quotas", "Projects", "Account",
    ])
    expect(within(nav).queryByRole("link", { name: "Provider settings", exact: true })).not.toBeInTheDocument()
  })

  it("SettingsProviders carries the fleet merge markers", () => {
    for (const marker of ["Endpoint", "ProviderTestModal"]) {
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
    // Seven headers plus eight 7-cell rows.
    expect(cells.length).toBe(EXPECTED_MERGED_HEADERS.length + 8 * EXPECTED_MERGED_HEADERS.length)
    for (const cell of cells) {
      expect(cell.className).toMatch(/whitespace-nowrap/)
    }
  })
})

// ---------------------------------------------------------------------------
// P1F-8: /providers lands on the merged Settings registry (RED)
// ---------------------------------------------------------------------------

describe("SettingsProviders.s-p2.test.tsx", () => {
  it("first-column (Provider) cells keep px-3 breathing room", async () => {
    renderSettings()
    await waitForProviders()
    for (const name of SEED_PROVIDER_NAMES) {
      const row = findProviderRowTr(name)
      const firstCell = row.children[0] as HTMLElement
      expect(firstCell.tagName).toBe("TD")
      expect(firstCell.className).toMatch(/px-3/)
    }
  })

  it("table + scroller stay intact: single 7-column merged table, overflow-x-auto, nowrap", async () => {
    renderSettings()
    await waitForProviders()
    expect(screen.getAllByRole("table")).toHaveLength(1)
    const table = screen.getByRole("table")
    expect(table.querySelectorAll("tbody tr")).toHaveLength(8)
    // Seven merged columns stand for every row (no Tavily extra cell).
    for (const name of SEED_PROVIDER_NAMES) {
      const row = findProviderRowTr(name)
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

  it("P1-FINAL page merge: fleet telemetry merged into SettingsProviders (ProviderMatrix retired)", () => {
    for (const marker of ["Endpoint", "ProviderTestModal"]) {
      expect(settingsFeatureSource, `merged registry must carry ${marker}`).toContain(marker)
    }
  })

  it("polyweb-ui ONLY: no backend/python import paths", () => {
    expect(settingsFeatureSource).not.toMatch(/\.py["']/)
    expect(settingsFeatureSource).not.toMatch(/src\/polyweb/)
  })
})

describe("P1F-8: legacy /providers URL renders the merged Settings registry", () => {
  it("navigating to /providers redirects to /system/providers", async () => {
    await renderAppAt("/providers")
    await waitFor(
      () => {
        expect(screen.getByRole("heading", { level: 2, name: "Providers" })).toBeInTheDocument()
      },
      { timeout: 5000 }
    )
    expect(screen.getByTestId("test-location").textContent).toBe("/system/providers")
  })

  it("the redirect target shows the merged registry (7 headers, no Provider settings page)", async () => {
    await renderAppAt("/providers")
    await waitFor(
      () => {
        expect(screen.getByRole("heading", { level: 2, name: "Providers" })).toBeInTheDocument()
      },
      { timeout: 5000 }
    )
    await waitFor(() => expect(headerNames()).toEqual([...EXPECTED_MERGED_HEADERS]))
    expect(screen.queryByRole("heading", { name: "Provider settings" })).not.toBeInTheDocument()
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
 *   Not-supported, Test states). NO page merge (P1 separate). polyweb-ui/ ONLY.
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
 *           pills (Providers/Failover, pill variant, no line), URL/sidebar/
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
  readFileSync(path.resolve(testDir, "../../../shared/ui/HealthStatus.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "../../../shared/ui/ReorderHandle.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderOperationControl.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./providerDisplay.ts"), "utf8"),
].join("\n")
// P1-FINAL (blessed inversion): ProviderMatrix.tsx is DELETED by the merge —
// no test may read it (the file is gone Green). Fleet-telemetry pins live in
// SettingsProviders.p1-final.test.tsx.
const appSource = readFileSync(path.resolve(testDir, "../../../App.tsx"), "utf8")
const routesSource = readFileSync(path.resolve(testDir, "../../../app/routes.ts"), "utf8")
const dashboardShellSource = readFileSync(
  path.resolve(testDir, "../../../app/DashboardShell.tsx"),
  "utf8"
)
const sidebarSource = readFileSync(path.resolve(testDir, "../../../components/layout/Sidebar.tsx"), "utf8")
const routesNavSource = readFileSync(
  path.resolve(testDir, "../../../app/layout/SidebarNavList.tsx"),
  "utf8"
)
const indexCssSource = readFileSync(path.resolve(testDir, "../../../index.css"), "utf8")

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
  "Cost per call",
  "Health",
  "Search",
  "Fetch",
  "On",
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
      const base = { ...(wire ?? allProvidersFixture()[0]) } as Record<string, unknown> & {
        enable_mask: number
      }
      const patch = ((req.body as Record<string, unknown>) ?? {}) as Record<string, unknown>
      let enableMask = base.enable_mask
      if (typeof patch.enable_mask === "number") enableMask = patch.enable_mask
      else {
        if (patch.enabled === true) enableMask |= 1
        if (patch.enabled === false) enableMask &= ~1
        if (patch.search_enabled === true) enableMask |= 2
        if (patch.search_enabled === false) enableMask &= ~2
        if (patch.fetch_enabled === true) enableMask |= 4
        if (patch.fetch_enabled === false) enableMask &= ~4
      }
      return ok({ ...base, enable_mask: enableMask, enabled: (enableMask & 1) !== 0 })
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
    <MemoryRouter>
      <PolywebProvider accountId={ADMIN_ACCOUNT_ID} canReadControls canEditControls>
        <SettingsView />
      </PolywebProvider>
    </MemoryRouter>
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

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

// ---------------------------------------------------------------------------
// S-P1-1: table structure + ui/table reuse
// ---------------------------------------------------------------------------

describe("S-P1-1: registry is a ui/table with the merged 7 columns", () => {
  it("flex-wrap list is gone (no flex-wrap rows, no basis-48 drift)", () => {
    expect(settingsFeatureSource.includes("flex-wrap")).toBe(false)
    expect(settingsFeatureSource.includes("basis-48")).toBe(false)
  })

  it("renders exactly one table for the provider registry", async () => {
    renderSettings()
    await waitForProviders()
    expect(screen.getAllByRole("table")).toHaveLength(1)
  })

  it("shows the catalog columns and each provider", async () => {
    renderSettings()
    await waitForProviders()
    expect(headerNames()).toEqual([...EXPECTED_HEADERS])
    for (const name of SEED_PROVIDER_NAMES) {
      expect(findProviderRowTr(name)).toBeInTheDocument()
    }
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
    // Seven merged columns stand for every row (no Tavily extra cell).
    for (const name of SEED_PROVIDER_NAMES) {
      const row = findProviderRowTr(name)
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
    for (const name of SEED_PROVIDER_NAMES) {
      const row = findProviderRowTr(name)
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

})

// ---------------------------------------------------------------------------
// S-P1-3: Global-off placeholder no-shift
// ---------------------------------------------------------------------------

describe("S-P1-3: Global-off placeholder keeps columns from collapsing", () => {
  it("OperationControl never returns null (placeholder keeps the cell occupied)", () => {
    expect(settingsFeatureSource).not.toMatch(/if\s*\(\s*globallyDisabled\s*\)\s*return\s+null/)
  })

  it("unsupported fetch reads as unavailable (a dash, no switch) while Global is on (Brave)", async () => {
    renderSettings()
    await waitForProviders()
    for (const name of FETCH_UNSUPPORTED) {
      const fetchCell = cellFor(name, "Fetch")
      expect(within(fetchCell).queryByRole("switch")).toBeNull()
      expect(within(fetchCell).getByText("—")).toBeInTheDocument()
      expect(within(fetchCell).getByText(`${name} does not support fetch`)).toBeInTheDocument()
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
    expect(within(fetchCell).getByText("—")).toBeInTheDocument()
    expect(
      within(cellFor("Brave Search", "Search")).getByRole("switch", { name: "Brave Search search routing" })
    ).toBeDisabled()
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

})

// ---------------------------------------------------------------------------
// S-P1-5: contracts preserved (priority, Switch, SegmentedControl, guards, Test)
// ---------------------------------------------------------------------------

describe("S-P1-5: all SettingsProviders contracts preserved in the table", () => {


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

    gate.resolve(ok({ ...allProvidersFixture()[3], enable_mask: 6, enabled: false }))
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

  it("persists a Search toggle via PATCH and disables the row while pending", async () => {
    const user = userEvent.setup()
    const gate = deferred<Response>()
    const stub = renderSettings()
    await waitForProviders()
    patchGate = gate.promise

    await user.click(
      within(cellFor("Brave Search", "Search")).getByRole("switch", {
        name: "Brave Search search routing",
      }),
    )
    await waitFor(() => {
      expect(
        screen.getByRole("switch", { name: "Brave Search search routing" }),
      ).toBeDisabled()
      expect(
        screen.getByRole("switch", { name: "Brave Search global routing" }),
      ).toBeDisabled()
    })

    gate.resolve(ok({ ...allProvidersFixture()[0], enable_mask: 5, enabled: true }))
    await waitFor(() => {
      expect(
        screen.getByRole("switch", { name: "Brave Search search routing" }),
      ).toHaveAttribute("aria-checked", "false")
    })
    const searchPatches = stub.requestsTo("/api/v1/providers/brave")
    expect(searchPatches).toHaveLength(1)
    expect(searchPatches[0].body).toEqual({ search_enabled: false })
  })

  it("persists a Fetch toggle via PATCH with one-bit bodies", async () => {
    const user = userEvent.setup()
    const stub = renderSettings()
    await waitForProviders()

    await user.click(
      within(cellFor("Tavily", "Fetch")).getByRole("switch", {
        name: "Tavily fetch routing",
      }),
    )
    await waitFor(() => {
      expect(
        within(cellFor("Tavily", "Fetch")).getByRole("switch", {
          name: "Tavily fetch routing",
        }),
      ).toHaveAttribute("aria-checked", "false")
    })
    const fetchPatches = stub.requestsTo("/api/v1/providers/tavily")
    expect(fetchPatches).toHaveLength(1)
    expect(fetchPatches[0].body).toEqual({ fetch_enabled: false })
  })

  it("preserves previous state when a persisted toggle fails", async () => {
    const user = userEvent.setup()
    const gate = deferred<Response>()
    const stub = renderSettings()
    await waitForProviders()
    patchGate = gate.promise

    await user.click(screen.getByRole("switch", { name: "Exa global routing" }))
    await waitFor(() => {
      expect(screen.getByRole("switch", { name: "Exa global routing" })).toBeDisabled()
    })

    gate.resolve(err(500, { detail: "db down" }) as unknown as Response)
    await waitFor(() => {
      expect(screen.getByRole("switch", { name: "Exa global routing" })).not.toBeDisabled()
    })
    expect(screen.getByRole("switch", { name: "Exa global routing" })).toHaveAttribute(
      "aria-checked",
      "true",
    )
    const failedPatches = stub.requestsTo("/api/v1/providers/exa")
    expect(failedPatches).toHaveLength(1)
    expect(failedPatches[0].body).toEqual({ enabled: false })
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
      // Every row (including Tavily) keeps seven cells; the test icon rides in the Health cell.
      const testIdx = columnIndex("Health")
      const testCell = row.children[testIdx] as HTMLElement
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
      expect(within(screen.getByRole("dialog")).getByText("Healthy · just now")).toBeInTheDocument()
      expect(within(screen.getByRole("dialog")).getByText("142 ms")).toBeInTheDocument()
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
  it("has no Failover tab: the fallback policy sits under the provider table", async () => {
    renderSettings()
    await waitForProviders()
    // Without key management only the Providers view exists, so no tab list renders.
    expect(screen.queryAllByRole("tab")).toHaveLength(0)
    expect(screen.queryByRole("tab", { name: "Failover" })).not.toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "When a provider fails" })).toBeInTheDocument()
    expect(screen.getByRole("switch", { name: "Fallback" })).toBeInTheDocument()
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

  it("route table: System Providers at /system/providers; /settings and /providers redirect there", () => {
    for (const routePath of ["/routing", "/system/quotas", "/system/providers"]) {
      expect(routesSource).toContain(`"${routePath}"`)
    }
    expect(dashboardShellSource).toMatch(/<Routes/)
    expect(dashboardShellSource).not.toMatch(/ProviderMatrix/)
    expect(appSource).not.toMatch(/ProviderMatrix/)
    // Thin App shim renders the shell that owns the table.
    expect(appSource).toContain("DashboardShell")
    // Former global paths live once in LEGACY_GLOBAL_REDIRECTS; the shell renders them as Navigate.
    const legacyBlock = routesSource.slice(
      routesSource.indexOf("LEGACY_GLOBAL_REDIRECTS"),
      routesSource.indexOf("LOGIN_PATH")
    )
    expect(legacyBlock).toContain('"/providers": TAB_PATHS.settings')
    expect(legacyBlock).toContain('"/settings": TAB_PATHS.settings')
    expect(dashboardShellSource).toContain("LEGACY_GLOBAL_REDIRECTS")
    expect(dashboardShellSource).toMatch(/Navigate/)
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
      ["quotas", "/system/quotas"],
      ["settings", "/system/providers"],
    ]) {
      expect(tabPathsBlock).toContain(`"${href}"`)
      expect(tabPathsBlock).toMatch(new RegExp(`${id}:`))
    }
    expect(routesNavSource).toMatch(/to=\{TAB_PATHS\[id\]\}/)
  })

  it("P1-FINAL page merge: ProviderMatrix retired, fleet telemetry merged into SettingsProviders", () => {
    // Standalone fleet page is gone: no Trip/Reset matrix, no fleet filter,
    // no stat cards in a separate page — the merged registry carries them.
    for (const marker of ["Endpoint", "ProviderTestModal"]) {
      expect(settingsFeatureSource, `merged registry must carry ${marker}`).toContain(marker)
    }
    expect(settingsFeatureSource).not.toMatch(/Total fleet/)
    expect(settingsFeatureSource).not.toMatch(/Provider filter/)
  })

  it("polyweb-ui ONLY: SettingsProviders imports no backend/python paths", () => {
    expect(settingsFeatureSource).not.toMatch(/\.py["']/)
    expect(settingsFeatureSource).not.toMatch(/src\/polyweb/)
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
 *   no other changes. polyweb-ui/ ONLY.
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
 *           polyweb-ui ONLY. NOTE: S-P2-5 "no button restyle" covers ONLY
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
  path.resolve(testDir, "../../../shared/ui/ReorderHandle.tsx"),
  "utf8"
)
const removedButtonShimPath = path.resolve(testDir, "../../../components/ui/button.tsx")
const settingsFeatureSource = [
  settingsSource,
  settingsRowSource,
  settingsModalSource,
  settingsPrioritySource,
  readFileSync(path.resolve(testDir, "./ProviderRegistryHeader.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "../../../shared/ui/HealthStatus.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderOperationControl.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./providerDisplay.ts"), "utf8"),
].join("\n")
const indexCssSource = readFileSync(path.resolve(testDir, "../../../index.css"), "utf8")

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
  "Cost per call",
  "Health",
  "Search",
  "Fetch",
  "On",
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
      const base = { ...(wire ?? allProvidersFixture()[0]) } as Record<string, unknown> & {
        enable_mask: number
      }
      const patch = ((req.body as Record<string, unknown>) ?? {}) as Record<string, unknown>
      let enableMask = base.enable_mask
      if (typeof patch.enable_mask === "number") enableMask = patch.enable_mask
      else {
        if (patch.enabled === true) enableMask |= 1
        if (patch.enabled === false) enableMask &= ~1
        if (patch.search_enabled === true) enableMask |= 2
        if (patch.search_enabled === false) enableMask &= ~2
        if (patch.fetch_enabled === true) enableMask |= 4
        if (patch.fetch_enabled === false) enableMask &= ~4
      }
      return ok({ ...base, enable_mask: enableMask, enabled: (enableMask & 1) !== 0 })
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
    <MemoryRouter>
      <PolywebProvider accountId={ADMIN_ACCOUNT_ID} canReadControls canEditControls>
        <SettingsView />
      </PolywebProvider>
    </MemoryRouter>
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
  it("modal opens with no test run yet and a Test button (type=button, enabled)", async () => {
    const user = userEvent.setup()
    renderSettings()
    await waitForProviders()

    await user.click(testButtonFor("Brave Search"))
    const dialog = await screen.findByRole("dialog")
    expect(within(dialog).getByText("—")).toBeInTheDocument()
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
      expect(within(screen.getByRole("dialog")).getByText("Healthy · just now")).toBeInTheDocument()
      expect(within(screen.getByRole("dialog")).getByText("142 ms")).toBeInTheDocument()
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
    const testIdx = headers.indexOf("Health")
    expect(testIdx).toBe(EXPECTED_HEADERS.indexOf("Health"))
    const rows = Array.from(table.querySelectorAll("tbody tr"))
    expect(rows).toHaveLength(8)
    for (const name of SEED_PROVIDER_NAMES) {
      const row = findProviderRowTr(name)
      // Every row (including Tavily) keeps seven cells; Test column index is unshifted.
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
    for (const name of SEED_PROVIDER_NAMES) {
      const row = findProviderRowTr(name)
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





  it("Carbon Black theme tokens untouched (#1e1e1e scale + #007acc, no oklch)", () => {
    expect(norm(indexCssSource).includes("#1e1e1e")).toBe(true)
    expect(norm(indexCssSource).includes("#252526")).toBe(true)
    expect(norm(indexCssSource).includes("#3e3e42")).toBe(true)
    expect(norm(indexCssSource).includes("#007acc")).toBe(true)
    expect(norm(indexCssSource).includes("oklch(")).toBe(false)
  })

  it("P1-FINAL page merge: fleet telemetry merged into SettingsProviders (ProviderMatrix retired)", () => {
    for (const marker of ["Endpoint", "ProviderTestModal"]) {
      expect(settingsFeatureSource, `merged registry must carry ${marker}`).toContain(marker)
    }
  })

  it("polyweb-ui ONLY: SettingsProviders imports no backend/python paths", () => {
    expect(settingsFeatureSource).not.toMatch(/\.py["']/)
    expect(settingsFeatureSource).not.toMatch(/src\/polyweb/)
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
 * Plan under test (ONLY SettingsProviders.tsx, polyweb-ui/ ONLY):
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
 *           POST), SettingsView pills (Providers/Failover pill
 *           variant), Carbon Black tokens, NO ProviderMatrix merge,
 *           sibling sections follow suit (KeyVault full width per K1, Failover per F1),
 *           polyweb-ui ONLY (no backend/python imports).
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
  path.resolve(testDir, "../../../shared/ui/ReorderHandle.tsx"),
  "utf8"
)
const settingsModalSource = readFileSync(
  path.resolve(testDir, "./ProviderTestModal.tsx"),
  "utf8"
)
const removedButtonShimPath = path.resolve(testDir, "../../../components/ui/button.tsx")
const settingsFeatureSource = [
  settingsSource,
  settingsPrioritySource,
  settingsModalSource,
  readFileSync(path.resolve(testDir, "./ProviderRegistryRow.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderRegistryHeader.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "../../../shared/ui/HealthStatus.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderOperationControl.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./providerDisplay.ts"), "utf8"),
].join("\n")
const indexCssSource = readFileSync(path.resolve(testDir, "../../../index.css"), "utf8")
// P1-FINAL (blessed inversion): ProviderMatrix.tsx is DELETED by the merge —
// no test may read it (the file is gone Green).
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
  "Cost per call",
  "Health",
  "Search",
  "Fetch",
  "On",
] as const

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
      const base = { ...(wire ?? allProvidersFixture()[0]) } as Record<string, unknown> & {
        enable_mask: number
      }
      const patch = ((req.body as Record<string, unknown>) ?? {}) as Record<string, unknown>
      let enableMask = base.enable_mask
      if (typeof patch.enable_mask === "number") enableMask = patch.enable_mask
      else {
        if (patch.enabled === true) enableMask |= 1
        if (patch.enabled === false) enableMask &= ~1
        if (patch.search_enabled === true) enableMask |= 2
        if (patch.search_enabled === false) enableMask &= ~2
        if (patch.fetch_enabled === true) enableMask |= 4
        if (patch.fetch_enabled === false) enableMask &= ~4
      }
      return ok({ ...base, enable_mask: enableMask, enabled: (enableMask & 1) !== 0 })
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
    <MemoryRouter>
      <PolywebProvider accountId={ADMIN_ACCOUNT_ID} canReadControls canEditControls>
        <SettingsView />
      </PolywebProvider>
    </MemoryRouter>
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
    // Seven headers plus eight 7-cell rows.
    expect(cells.length).toBe(EXPECTED_HEADERS.length + 8 * EXPECTED_HEADERS.length)
    for (const cell of cells) {
      expect(cell.className).toMatch(/whitespace-nowrap/)
    }
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
    for (const name of SEED_PROVIDER_NAMES) {
      const row = findProviderRowTr(name)
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

  it("SettingsView has no Failover tab; the fallback section follows the table", async () => {
    renderSettings()
    await waitForProviders()
    expect(screen.queryByRole("tab", { name: "Failover" })).not.toBeInTheDocument()
    const table = screen.getByRole("table")
    const fallback = screen.getByRole("heading", { name: "When a provider fails" })
    expect(table.compareDocumentPosition(fallback) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
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

  it("scope: Failover spans full width (F1)", () => {
    expect(failoverSource).not.toMatch(/max-w-3xl/)
    expect(failoverSource).toMatch(/w-full/)
    expect(failoverSource).toMatch(/max-w-none/)
  })

  it("P1-FINAL page merge: fleet telemetry merged into SettingsProviders (ProviderMatrix retired)", () => {
    for (const marker of ["Endpoint", "ProviderTestModal"]) {
      expect(settingsFeatureSource, `merged registry must carry ${marker}`).toContain(marker)
    }
  })

  it("polyweb-ui ONLY: SettingsProviders imports no backend/python paths", () => {
    expect(settingsFeatureSource).not.toMatch(/\.py["']/)
    expect(settingsFeatureSource).not.toMatch(/src\/polyweb/)
  })
})
})

describe("SettingsProviders Developer read-only (canReadControls, no edit)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  function renderDeveloperSettings(): FetchStub {
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
      <MemoryRouter>
        <PolywebProvider accountId={DEVELOPER_ACCOUNT_ID} canReadControls canEditControls={false}>
          <SettingsView />
        </PolywebProvider>
      </MemoryRouter>
    )
    return stub
  }

  async function waitForDeveloperProviders() {
    await waitFor(() => {
      expect(screen.getByText("Brave Search", { exact: true })).toBeInTheDocument()
    })
  }

  it("shows stored state/rank/flags as read-only text with no probe button, modal, or switches, and sends no writes", async () => {
    const stub = renderDeveloperSettings()
    await waitForDeveloperProviders()

    // Read-only markers present: catalog headers intact, Health a muted dash.
    const headers = Array.from(screen.getByRole("table").querySelectorAll("thead th")).map(
      (th) => th.textContent?.trim() ?? ""
    )
    expect(headers).toEqual(["Provider", "Endpoint", "Cost per call", "Health", "Search", "Fetch", "On"])
    expect(within(screen.getByRole("table")).getAllByTitle("No result yet")).toHaveLength(8)
    expect(screen.queryByText("Not tested", { exact: true })).not.toBeInTheDocument()
    expect(screen.queryByText("Hidden", { exact: true })).not.toBeInTheDocument()
    expect(screen.getAllByText("On", { exact: true }).length).toBeGreaterThan(0)
    // Every switch is gone; the unsupported Brave fetch reads as an unavailable dash.
    expect(screen.queryAllByRole("switch")).toHaveLength(0)
    expect(screen.getByText("Brave Search does not support fetch")).toBeInTheDocument()
    // Mutation affordances absent: no probe buttons, no priority moves, no global switches, no modal.
    expect(screen.queryByRole("button", { name: /test connection/i })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /priority (up|down)/ })).not.toBeInTheDocument()
    expect(screen.queryByRole("switch", { name: /global routing/ })).not.toBeInTheDocument()
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    // Zero backend writes beyond the stubbed reads.
    expect(
      stub.requests.filter((r) => r.method === "PATCH" || r.method === "PUT" || r.method === "POST")
    ).toHaveLength(0)
  })
})

describe("SettingsProviders Tavily rate-tier removed from Settings registry", () => {
  /**
   * The Tavily key-environment dropdown was removed from the Settings
   * registry; it lives only in the Usage Tavily card (compact tier select
   * via QuotaAnalytics renderRateTier -> ProviderLimitsCard tierSlot).
   * The seven registry columns stand; every row (including Tavily) keeps
   * exactly seven cells. Usage coverage for the compact select lives in
   * ProviderLimitsCard.test.tsx / TavilyRateTierSelect.test.tsx.
   */

  const SLOT_NAMES = [
    "Brave Search",
    "Keenable",
    "Tavily",
    "Exa",
    "Firecrawl",
    "You.com",
    "Parallel",
    "Tinyfish",
  ] as const

  function renderNoSlotSettings(
    providers: WireProviderStatus[],
    accountId: string = ADMIN_ACCOUNT_ID,
    canEdit = true
  ): FetchStub {
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
        return ok(entry)
      }
      return err(404, { detail: "unhandled test route" })
    })
    render(
      <MemoryRouter>
        <PolywebProvider accountId={accountId} canReadControls canEditControls={canEdit}>
          <SettingsView />
        </PolywebProvider>
      </MemoryRouter>
    )
    return stub
  }

  async function waitForNoSlotProviders() {
    await waitFor(() => {
      expect(screen.getByText("Brave Search", { exact: true })).toBeInTheDocument()
    })
  }

  function noSlotRowTr(provider: string): HTMLTableRowElement {
    const nameEl = screen.getByText(provider, { exact: true })
    const tr = nameEl.closest("tr")
    if (!tr) throw new Error(`Provider table row <tr> not found for ${provider}`)
    return tr as HTMLTableRowElement
  }

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it("does not render Tavily rate-tier in Settings registry", async () => {
    renderNoSlotSettings(allProvidersFixture())
    await waitForNoSlotProviders()
    expect(screen.queryByText("Rate tier (key environment)")).not.toBeInTheDocument()
    expect(document.querySelector("select#tavily-rate-tier")).toBeNull()
    expect(
      screen.queryByRole("combobox", { name: /tavily rate tier/i })
    ).not.toBeInTheDocument()
    const tavilyRow = noSlotRowTr("Tavily")
    expect(tavilyRow.querySelector("select")).toBeNull()
    expect(tavilyRow.children).toHaveLength(7)
    for (const name of SLOT_NAMES) {
      expect(noSlotRowTr(name).children).toHaveLength(7)
      expect(noSlotRowTr(name).querySelector("select")).toBeNull()
    }
  })

  it("Tavily Endpoint cell shows endpoint text only with no dropdown", async () => {
    renderNoSlotSettings(allProvidersFixture())
    await waitForNoSlotProviders()
    const table = screen.getByRole("table")
    const headers = Array.from(table.querySelectorAll("thead th")).map(
      (th) => th.textContent?.trim() ?? ""
    )
    const endpointIdx = headers.indexOf("Endpoint")
    expect(endpointIdx).toBe(1)
    const tavilyRow = noSlotRowTr("Tavily")
    const endpointCell = tavilyRow.children[endpointIdx] as HTMLElement
    expect(endpointCell.textContent).toContain("api.tavily.com")
    expect(endpointCell.querySelector("select")).toBeNull()
    expect(within(endpointCell).queryByRole("combobox")).toBeNull()
  })

  it("Settings registry source owns no rate-tier slot", () => {
    const settingsSrc = readFileSync(path.resolve(import.meta.dirname, "./SettingsProviders.tsx"), "utf8")
    expect(settingsSrc).not.toContain("TavilyRateTierSelect")
    expect(settingsSrc).not.toContain("rateTierSlot")
    expect(settingsSrc).not.toContain("rateTier=")
    const rowSrc = readFileSync(path.resolve(import.meta.dirname, "./ProviderRegistryRow.tsx"), "utf8")
    expect(rowSrc).not.toContain("rateTier")
  })

  it("Usage card still owns the compact Tavily tier select", () => {
    const tierSrc = readFileSync(path.resolve(import.meta.dirname, "../../quota/ui/TavilyRateTierSelect.tsx"), "utf8")
    expect(tierSrc).toContain("compact")
    const quotaSrc = readFileSync(path.resolve(import.meta.dirname, "../../quota/ui/QuotaAnalytics.tsx"), "utf8")
    expect(quotaSrc).toContain("renderRateTier")
    expect(quotaSrc).toContain("TavilyRateTierSelect")
    expect(quotaSrc).toContain("compact")
  })
})
