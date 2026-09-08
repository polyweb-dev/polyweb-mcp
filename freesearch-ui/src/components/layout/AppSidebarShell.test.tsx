import React from "react"
import { readFileSync } from "node:fs"
import path from "node:path"
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, useLocation } from "react-router"
import App from "@/App"
import { installFetchStub, ok, err } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
} from "@/test/backendFixtures"

/**
 * C4 URL routing — App shell over the route table (REWRITTEN, Red phase).
 *
 * Blessed churn (NOT weakening): the C3-REWORK AC-SB-8d plain-button pin is
 * VOID. The shell keeps the flex-row aside+main layout, but workspace
 * switching is router navigation:
 *   - sidebar nav items are links (getByRole button->link) with exact hrefs;
 *   - switching views changes the URL through the route table;
 *   - react-router is a dependency; App source declares Routes.
 *
 * Preserved: AC-SB-8a (flex-row aside+main), AC-SB-8b (no legacy header),
 * AC-SB-8c (six links swap intact views — now link queries + URL asserts),
 * AC-SB-8e (PillTabs gold standard untouched), AC-SB-8f (Sidebar wiring +
 * collapse toggle). TabId unchanged — quotas renders at /usage.
 */

const testDir = import.meta.dirname
const appSource = readFileSync(path.resolve(testDir, "../../App.tsx"), "utf8")
const packageJsonRaw = readFileSync(
  path.resolve(testDir, "../../../package.json"),
  "utf8"
)
const packageJson = JSON.parse(packageJsonRaw) as {
  dependencies?: Record<string, string>
  devDependencies?: Record<string, string>
}

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="test-location">{location.pathname}</div>
}

function renderApp(route = "/playground") {
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
  return render(
    <MemoryRouter initialEntries={[route]}>
      <App />
      <LocationProbe />
    </MemoryRouter>
  )
}

function testPath(): string {
  return screen.getByTestId("test-location").textContent ?? ""
}

const EXPECTED_VIEWS: Array<{ link: string; heading: string; path: string }> = [
  { link: "Playground", heading: "Search Playground", path: "/playground" },
  { link: "Providers", heading: "Providers", path: "/providers" },
  { link: "Routing", heading: "Routing", path: "/routing" },
  { link: "Usage", heading: "Usage", path: "/usage" },
  { link: "Activity", heading: "Activity", path: "/activity" },
  { link: "Settings", heading: "Settings", path: "/settings" },
]

beforeEach(() => {
  window.localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe("AC-SB-8a: App is a flex-row shell with aside + main", () => {
  it("renders the sidebar aside and the main landmark", async () => {
    renderApp()
    expect(document.querySelector("aside")).not.toBeNull()
    expect(screen.getByRole("main")).toBeInTheDocument()
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: "Search Playground" })
      ).toBeInTheDocument()
    })
  })

  it("shell lays out horizontally (flex-row), not the legacy flex-col stack", () => {
    renderApp()
    const aside = document.querySelector("aside")
    expect(aside).not.toBeNull()
    const shell = aside!.parentElement as HTMLElement
    expect(shell.className).toMatch(/flex/)
    expect(shell.className).toMatch(/flex-row/)
    expect(shell.className).not.toMatch(/flex-col/)
  })

  it("aside and main share the same horizontal shell", () => {
    renderApp()
    const shell = (document.querySelector("aside") as HTMLElement)
      .parentElement as HTMLElement
    expect(shell.className).toMatch(/flex-row/)
    expect(shell.contains(screen.getByRole("main"))).toBe(true)
  })
})

describe("AC-SB-8b: legacy header topbar is gone", () => {
  it("renders no <header> element", () => {
    renderApp()
    expect(document.querySelector("header")).toBeNull()
  })

  it("App source no longer renders the Header topbar", () => {
    expect(appSource.includes("<Header")).toBe(false)
    expect(appSource).not.toMatch(/from\s+["']@\/components\/layout\/Header["']/)
  })
})

describe("AC-SB-8c (C4): six sidebar links swap intact views via the URL", () => {
  it("sidebar exposes all six workspaces as links with exact route hrefs", () => {
    renderApp()
    const nav = screen.getByRole("navigation", { name: "Primary" })
    for (const { link, path } of EXPECTED_VIEWS) {
      expect(
        within(nav).getByRole("link", { name: link, exact: true })
      ).toHaveAttribute("href", path)
    }
  })

  it.each(EXPECTED_VIEWS)(
    "sidebar '$link' navigates to '$path' showing the '$heading' view",
    async ({ link, heading, path }) => {
      const user = userEvent.setup()
      renderApp("/playground")
      await user.click(
        within(screen.getByRole("navigation", { name: "Primary" })).getByRole(
          "link",
          { name: link, exact: true }
        )
      )
      await waitFor(() => {
        expect(
          within(screen.getByRole("main")).getByRole("heading", {
            name: heading,
          })
        ).toBeInTheDocument()
      })
      expect(testPath()).toBe(path)
    }
  )

  it("full click-through visits every view with exactly one active marker", async () => {
    const user = userEvent.setup()
    renderApp("/playground")
    for (const { link, heading, path } of EXPECTED_VIEWS) {
      await user.click(
        within(screen.getByRole("navigation", { name: "Primary" })).getByRole(
          "link",
          { name: link, exact: true }
        )
      )
      await waitFor(() => {
        expect(
          screen.getByRole("heading", { name: heading })
        ).toBeInTheDocument()
      })
      expect(testPath()).toBe(path)
      expect(
        document.querySelectorAll('aside [aria-current="page"]')
      ).toHaveLength(1)
    }
  })
})

describe("AC-SB-8d (C4): shell keeps the link+router contract", () => {
  it("sidebar nav has links with hrefs and no button nav items", () => {
    renderApp()
    const aside = document.querySelector("aside") as HTMLElement
    const nav = within(aside).getByRole("navigation", { name: "Primary" })
    expect(within(nav).getAllByRole("link")).toHaveLength(6)
    expect(within(nav).queryByRole("button")).not.toBeInTheDocument()
    expect(within(aside).queryByRole("tab")).not.toBeInTheDocument()
    expect(within(aside).queryByRole("tablist")).not.toBeInTheDocument()
    expect(within(aside).queryByRole("tabpanel")).not.toBeInTheDocument()
  })

  it("switching views changes the URL through the route table", async () => {
    const user = userEvent.setup()
    renderApp("/playground")
    expect(testPath()).toBe("/playground")
    for (const { link, path } of EXPECTED_VIEWS) {
      await user.click(
        within(screen.getByRole("navigation", { name: "Primary" })).getByRole(
          "link",
          { name: link, exact: true }
        )
      )
      expect(testPath()).toBe(path)
    }
    const allDeps = {
      ...(packageJson.dependencies ?? {}),
      ...(packageJson.devDependencies ?? {}),
    }
    expect(Object.keys(allDeps)).toContain("react-router")
    expect(appSource).toMatch(/react-router/i)
  })

  it("App source declares the Routes table with redirect + catch-all", () => {
    expect(appSource).toMatch(/<Routes/)
    expect(appSource).toMatch(/<Route/)
    for (const routePath of [
      "/playground",
      "/providers",
      "/routing",
      "/usage",
      "/activity",
      "/settings",
    ]) {
      expect(appSource).toContain(`"${routePath}"`)
    }
    // Root redirect and unknown-path fallback both land on the playground.
    expect(appSource).toMatch(/<Navigate/)
    expect(appSource).toContain('"/playground"')
  })
})

describe("AC-SB-8e: PillTabs gold standard untouched", () => {
  it("Routing view still exposes Strategy/Simulator/Ranks/Resilience pill tabs", async () => {
    const user = userEvent.setup()
    renderApp("/playground")
    await user.click(
      within(screen.getByRole("navigation", { name: "Primary" })).getByRole(
        "link",
        { name: "Routing", exact: true }
      )
    )
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: "Routing" })
      ).toBeInTheDocument()
    })
    const pillList = document.querySelector(
      '[data-slot="tabs-list"][data-variant="pill"]'
    )
    expect(pillList).not.toBeNull()
    expect(
      within(pillList as HTMLElement)
        .getAllByRole("tab")
        .map((t) => t.textContent)
    ).toEqual(["Strategy", "Simulator", "Ranks", "Resilience"])
  })

  it("Settings view still exposes Providers/Keys/Failover pill tabs", async () => {
    const user = userEvent.setup()
    renderApp("/playground")
    await user.click(
      within(screen.getByRole("navigation", { name: "Primary" })).getByRole(
        "link",
        { name: "Settings", exact: true }
      )
    )
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: "Settings" })
      ).toBeInTheDocument()
    })
    const pillList = document.querySelector(
      '[data-slot="tabs-list"][data-variant="pill"]'
    )
    expect(pillList).not.toBeNull()
    expect(
      within(pillList as HTMLElement)
        .getAllByRole("tab")
        .map((t) => t.textContent)
    ).toEqual(["Providers", "Keys", "Failover"])
  })
})

describe("AC-SB-8f: App source wires Sidebar into the flex-row shell", () => {
  it("App source imports and renders the Sidebar", () => {
    expect(appSource).toMatch(
      /from\s+["']@\/components\/layout\/Sidebar["']/
    )
    expect(appSource.includes("<Sidebar")).toBe(true)
  })

  it("App source declares the horizontal shell", () => {
    expect(appSource).toMatch(/flex-row/)
  })

  it("App exposes the sidebar collapse toggle", async () => {
    const user = userEvent.setup()
    renderApp()
    const toggle = screen.getByRole("button", {
      name: "Collapse sidebar",
      exact: true,
    })
    expect(toggle).toBeInTheDocument()
    await user.click(toggle)
    expect(
      (document.querySelector("aside") as HTMLElement).className
    ).toMatch(/w-16/)
  })
})
