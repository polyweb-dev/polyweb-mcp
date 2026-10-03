import React from "react"
import { readFileSync, existsSync } from "node:fs"
import path from "node:path"
import { describe, expect, it, afterEach, vi } from "vitest"
import { render, screen, within, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { SettingsView } from "./SettingsView"
import { installFetchStub, ok, err, deferred, type FetchStub } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
} from "@/test/backendFixtures"

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
const FETCH_SUPPORTED = [
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

  it("renders 8 body rows (one per backend provider)", async () => {
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
// S-P1-2: per-column x-position equality (<=1px across 8 rows)
// ---------------------------------------------------------------------------

describe("S-P1-2: per-column x-position equality across 8 rows (<=1px)", () => {
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

  it("measured left edges match within 1px per column across all 8 rows", async () => {
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
  it("shows priorities P1..P8 with bounded up/down controls per row", async () => {
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
      screen.getByRole("button", { name: "Move Tinyfish priority up" })
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
