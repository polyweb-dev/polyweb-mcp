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
 *         unknown-path catch-all to /playground; quotas maps to /usage.
 *   C4-5  Sidebar renders NavLink (role link) with exact `to` targets and
 *         no plain-button nav items.
 *
 * P1-FINAL (blessed inversion, NOT a regression): the standalone Providers
 * page is retired — five workspace routes, no /providers view, legacy
 * /providers redirects to /settings, providers TabId retired.
 */

const layoutDir = import.meta.dirname
const uiRoot = path.resolve(layoutDir, "../../..")
const appSource =
  readFileSync(path.join(uiRoot, "src/App.tsx"), "utf8") +
  "\n" +
  readFileSync(
    path.join(uiRoot, "src/components/layout/DashboardContent.tsx"),
    "utf8"
  )
const mainSource = readFileSync(path.join(uiRoot, "src/main.tsx"), "utf8")
const sidebarSource = readFileSync(
  path.join(uiRoot, "src/components/layout/Sidebar.tsx"),
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
    expect(appSource).toMatch(/<Routes/)
    expect(appSource).toMatch(/<Route/)
    expect(appSource).toMatch(/<Navigate/)
    expect(appSource).toMatch(/from\s+["']react-router["']/)
  })

  it("declares every route-table path exactly once", () => {
    for (const routePath of ROUTE_PATHS) {
      expect(appSource).toContain(`"${routePath}"`)
    }
  })

  it("redirects the root path to the playground", () => {
    expect(appSource).toContain('"/playground"')
    expect(appSource).toMatch(/path="\/"[^>]*element=\{[^}]*Navigate/)
  })

  it("catches unknown paths back to the playground", () => {
    expect(appSource).toMatch(/path="\*"[^>]*element=\{[^}]*Navigate/)
  })

  it("maps the quotas TabId to the /usage path (no /quotas route)", () => {
    expect(appSource).toContain('"/usage"')
    expect(appSource).not.toContain('"/quotas"')
    expect(appSource).toContain('"quotas"')
  })

  it("P1-FINAL: retires the providers view — no ProviderMatrix route", () => {
    expect(appSource).not.toMatch(/ProviderMatrix/)
  })

  it("P1-FINAL: redirects the legacy /providers path to /settings", () => {
    expect(appSource).toContain('"/providers"')
    const idx = appSource.indexOf('"/providers"')
    const window_ = appSource.slice(Math.max(0, idx - 120), idx + 300)
    expect(window_).toMatch(/Navigate/)
    expect(window_).toContain('"/settings"')
  })
})

describe("C4-5: Sidebar NavLink contract in source", () => {
  it("imports NavLink from react-router", () => {
    expect(sidebarSource).toMatch(/NavLink/)
    expect(sidebarSource).toMatch(/from\s+["']react-router["']/)
  })

  it("binds every nav item to its exact route target", () => {
    for (const routePath of ROUTE_PATHS) {
      expect(sidebarSource).toContain(`"${routePath}"`)
    }
  })

  it("P1-FINAL: sidebar drops the retired /providers target", () => {
    expect(sidebarSource).not.toContain('"/providers"')
    expect(sidebarSource).not.toContain('"providers"')
  })

  it("renders no plain-button nav items (controls stay buttons)", () => {
    // NavList must not render <button> for the six workspaces; the only
    // <button> elements left are the collapse toggle + drawer controls.
    const navListBlock = sidebarSource.slice(
      sidebarSource.indexOf("function NavList"),
      sidebarSource.indexOf("function Brand")
    )
    expect(navListBlock).not.toContain("<button")
    expect(navListBlock).toContain("<NavLink")
  })
})
