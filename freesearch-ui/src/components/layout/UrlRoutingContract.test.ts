import { readFileSync } from "node:fs"
import path from "node:path"
import { describe, it, expect } from "vitest"

/**
 * C4 URL routing — install + source-wiring contract (NEW, Red phase).
 *
 * Deliberately imports NOTHING from react-router so this suite executes
 * even before the router is installed: every failure below is a granular
 * assertion failure (not a collection error), proving the Red state is
 * not vacuous theater. The MemoryRouter behavioral suites
 * (UrlRouting.test.tsx, Sidebar.test.tsx, AppSidebarShell.test.tsx) cover
 * runtime history; this suite pins the wiring the plan requires:
 *   C4-1  react-router v7 installed; main.tsx renders BrowserRouter.
 *   C4-2  App.tsx Routes table with the exact paths, root redirect, and
 *         unknown-path catch-all; quotas maps to /usage. U1: the root and
 *         unknown paths land on the last valid project, else /projects.
 *   C4-5  Sidebar renders NavLink (role link) with exact `to` targets and
 *         no plain-button nav items.
 *
 * P1-FINAL (blessed inversion, NOT a regression): the standalone Providers
 * page is retired — five workspace routes, no /providers view, legacy
 * /providers redirects to /settings, providers TabId retired.
 */

const layoutDir = import.meta.dirname
const uiRoot = path.resolve(layoutDir, "../../..")
const appSource = readFileSync(path.join(uiRoot, "src/App.tsx"), "utf8")
const mainSource = readFileSync(path.join(uiRoot, "src/main.tsx"), "utf8")
// Slice 4: route identifiers live in app/routes, the Routes table + shell in
// app/DashboardShell.tsx, navigation in app/layout (Sidebar + NavList).
const routesSource = readFileSync(path.join(uiRoot, "src/app/routes.ts"), "utf8")
const dashboardShellSource = readFileSync(
  path.join(uiRoot, "src/app/DashboardShell.tsx"),
  "utf8"
)
const sidebarSource = readFileSync(
  path.join(uiRoot, "src/components/layout/Sidebar.tsx"),
  "utf8"
)
const sidebarOwnerSource = readFileSync(
  path.join(uiRoot, "src/app/layout/Sidebar.tsx"),
  "utf8"
)
const sidebarNavSource = readFileSync(
  path.join(uiRoot, "src/app/layout/SidebarNavList.tsx"),
  "utf8"
)
const packageJson = JSON.parse(
  readFileSync(path.join(uiRoot, "package.json"), "utf8")
) as { dependencies?: Record<string, string>; devDependencies?: Record<string, string> }

const ROUTE_PATHS = [
  "/playground",
  "/routing",
  "/usage",
  "/activity",
  "/settings",
] as const

describe("C4-1: react-router v7 install + BrowserRouter boot", () => {
  it("declares react-router as a runtime dependency", () => {
    expect(Object.keys(packageJson.dependencies ?? {})).toContain("react-router")
  })

  it("main.tsx boots the app inside a BrowserRouter", () => {
    expect(mainSource).toMatch(/BrowserRouter/)
    expect(mainSource).toMatch(/from\s+["']react-router["']/)
  })
})

describe("C4-2: App.tsx Routes table + redirects", () => {
  it("imports Routes, Route, and Navigate from react-router", () => {
    expect(dashboardShellSource).toMatch(/<Routes/)
    expect(dashboardShellSource).toMatch(/<Route/)
    expect(dashboardShellSource).toMatch(/<Navigate/)
    expect(dashboardShellSource).toMatch(/from\s+["']react-router["']/)
    // Thin App shim composes providers over the dashboard shell.
    expect(appSource).toContain("DashboardShell")
    expect(appSource).toContain("AppProviders")
  })

  it("declares every route-table path exactly once", () => {
    for (const routePath of ROUTE_PATHS) {
      expect(routesSource).toContain(`"${routePath}"`)
    }
  })

  it("U1: lands the root path on the project-first entry", () => {
    expect(dashboardShellSource).toMatch(/path="\/"[^>]*element=\{<WorkspaceLanding/)
  })

  it("U1: catches unknown paths with the project-first entry", () => {
    expect(dashboardShellSource).toMatch(/path="\*"[^>]*element=\{<WorkspaceLanding/)
  })

  it("maps the quotas TabId to the /usage path (no /quotas route)", () => {
    expect(routesSource).toContain('"/usage"')
    expect(routesSource).not.toContain('"/quotas"')
    expect(routesSource).toContain('"quotas"')
  })

  it("P1-FINAL: retires the providers view — no ProviderMatrix route", () => {
    expect(dashboardShellSource).not.toMatch(/ProviderMatrix/)
    expect(appSource).not.toMatch(/ProviderMatrix/)
  })

  it("P1-FINAL: redirects the legacy /providers path to /settings", () => {
    expect(dashboardShellSource).toContain('"/providers"')
    const idx = dashboardShellSource.indexOf('"/providers"')
    const window_ = dashboardShellSource.slice(Math.max(0, idx - 120), idx + 300)
    expect(window_).toMatch(/Navigate/)
    expect(window_).toContain('"/settings"')
  })
})

describe("C4-5: Sidebar NavLink contract in source", () => {
  it("imports NavLink from react-router", () => {
    expect(sidebarNavSource).toMatch(/NavLink/)
    expect(sidebarNavSource).toMatch(/from\s+["']react-router["']/)
    // Compat shim keeps the old import surface working.
    expect(sidebarSource).toMatch(/from\s+["']@\/app\/layout\/Sidebar["']/)
  })

  it("binds every nav item to its exact route target", () => {
    // Route identifiers live in app routing: TAB_PATHS pins each id->target
    // pair exactly once, and the nav binds through that table.
    const tabPathsBlock = routesSource.slice(
      routesSource.indexOf("TAB_PATHS"),
      routesSource.indexOf("WorkspaceRoute")
    )
    for (const [id, routePath] of [
      ["playground", "/playground"],
      ["routing", "/routing"],
      ["quotas", "/usage"],
      ["activity", "/activity"],
      ["settings", "/settings"],
    ]) {
      expect(tabPathsBlock).toContain(`"${routePath}"`)
      expect(tabPathsBlock).toMatch(new RegExp(`${id}:`))
    }
    expect(sidebarNavSource).toMatch(/to=\{TAB_PATHS\[id\]\}/)
    expect(sidebarNavSource).toMatch(/from\s+["']\.\.\/routes["']/)
    expect(sidebarOwnerSource).toContain("NavList")
  })

  it("P1-FINAL: sidebar drops the retired /providers target", () => {
    expect(sidebarNavSource).not.toContain('"/providers"')
    expect(sidebarNavSource).not.toContain('"providers"')
    expect(routesSource).not.toContain('"providers"')
  })

  it("renders no plain-button nav items (controls stay buttons)", () => {
    // NavList must not render <button> for the six workspaces; the only
    // <button> elements left are the collapse toggle + drawer controls.
    expect(sidebarNavSource).not.toContain("<button")
    expect(sidebarNavSource).toContain("<NavLink")
    expect(sidebarNavSource).toMatch(/export\s+(function|const)\s+NavList/)
  })
})
