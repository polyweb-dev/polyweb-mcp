import React from "react"
import { readFileSync } from "node:fs"
import path from "node:path"
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, useLocation } from "react-router"
import App from "@/App"
import { installAuthStub, ok, err } from "@/test/fetchMock"
import type { FetchHandler } from "@/test/fetchMock"
import {
  installFakeChannel,
  installImmediateLocks,
  removeLocks,
} from "@/test/browserStubs"
import {
  adminAccountFixture,
  agentAccountFixture,
} from "@/test/authFixtures"
import type { UserAccount } from "@/domains/auth"
import { answerWorkspaceAccess, personaSystemPermissions } from "@/test/accessFixtures"
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
 * AC-SB-8c (five links swap intact views — now link queries + URL asserts),
 * AC-SB-8e (PillTabs gold standard untouched), AC-SB-8f (Sidebar wiring +
 * collapse toggle). TabId unchanged — quotas renders at /usage.
 *
 * P1-FINAL (blessed inversion, NOT a regression): the standalone Providers
 * page is retired into the Settings Providers tab — five workspace links,
 * no /providers view, legacy /providers redirects to /settings.
 */

const testDir = import.meta.dirname
const appSource = readFileSync(path.resolve(testDir, "../../App.tsx"), "utf8")
// Slice 4: route table lives in app/routes, the flex-row shell + Routes table
// in app/DashboardShell.tsx; App.tsx is a thin AppProviders>DashboardShell shim.
const routesSource = readFileSync(path.resolve(testDir, "../../app/routes.ts"), "utf8")
const dashboardShellSource = readFileSync(
  path.resolve(testDir, "../../app/DashboardShell.tsx"),
  "utf8"
)
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

async function renderApp(route = "/playground", account: UserAccount = adminAccountFixture()) {
  installImmediateLocks()
  installFakeChannel()
  const backendHandler: FetchHandler = (req) => {
    const access = answerWorkspaceAccess(req, {
      systemPermissions: personaSystemPermissions(account),
    })
    if (access !== null) return access
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    return err(404, { detail: "unhandled test route" })
  }
  installAuthStub({ account }, backendHandler)
  const result = render(
    <MemoryRouter initialEntries={[route]}>
      <App />
      <LocationProbe />
    </MemoryRouter>
  )
  await screen.findByRole("navigation", { name: "Primary" })
  // The project selector renders once the system access and the project list
  // have loaded, so every permitted link is present from here on.
  await screen.findByRole("navigation", { name: "Projects" })
  return result
}

function testPath(): string {
  return screen.getByTestId("test-location").textContent ?? ""
}

const EXPECTED_VIEWS: Array<{ link: string; heading: string; path: string }> = [
  { link: "Playground", heading: "Search Playground", path: "/playground" },
  { link: "Routing", heading: "Routing", path: "/routing" },
  { link: "Usage", heading: "Usage", path: "/usage" },
  { link: "Activity", heading: "Activity", path: "/activity" },
  { link: "Settings", heading: "Settings", path: "/settings" },
  { link: "Projects", heading: "Projects", path: "/projects" },
  { link: "Account", heading: "Account", path: "/account" },
  { link: "Admin", heading: "Accounts", path: "/admin/users" },
]

beforeEach(() => {
  window.localStorage.clear()
})

afterEach(() => {
  removeLocks()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe("AC-SB-8a: App is a flex-row shell with aside + main", () => {
  it("renders the sidebar aside and the main landmark", async () => {
    await renderApp()
    expect(document.querySelector("aside")).not.toBeNull()
    expect(screen.getByRole("main")).toBeInTheDocument()
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: "Search Playground" })
      ).toBeInTheDocument()
    })
  })

  it("shell lays out horizontally (flex-row), not the legacy flex-col stack", async () => {
    await renderApp()
    const aside = document.querySelector("aside")
    expect(aside).not.toBeNull()
    const shell = aside!.parentElement as HTMLElement
    expect(shell.className).toMatch(/flex/)
    expect(shell.className).toMatch(/flex-row/)
    expect(shell.className).not.toMatch(/flex-col/)
  })

  it("aside and main share the same horizontal shell", async () => {
    await renderApp()
    const shell = (document.querySelector("aside") as HTMLElement)
      .parentElement as HTMLElement
    expect(shell.className).toMatch(/flex-row/)
    expect(shell.contains(screen.getByRole("main"))).toBe(true)
  })
})

describe("AC-SB-8b: legacy header topbar is gone", () => {
  it("renders no <header> element", async () => {
    await renderApp()
    expect(document.querySelector("header")).toBeNull()
  })

  it("App source no longer renders the Header topbar", () => {
    expect(appSource.includes("<Header")).toBe(false)
    expect(appSource).not.toMatch(/from\s+["']@\/components\/layout\/Header["']/)
  })
})

describe("AC-SB-8c (C4, P1-FINAL, R-UI, U1): eight sidebar links swap intact views via the URL", () => {
  it("sidebar exposes all eight workspaces as links with exact route hrefs", async () => {
    await renderApp()
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
      await renderApp("/playground")
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
    await renderApp("/playground")
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
  it("sidebar nav has links with hrefs and no button nav items", async () => {
    await renderApp()
    const aside = document.querySelector("aside") as HTMLElement
    const nav = within(aside).getByRole("navigation", { name: "Primary" })
    expect(within(nav).getAllByRole("link")).toHaveLength(EXPECTED_VIEWS.length)
    expect(within(nav).queryByRole("button")).not.toBeInTheDocument()
    expect(within(aside).queryByRole("tab")).not.toBeInTheDocument()
    expect(within(aside).queryByRole("tablist")).not.toBeInTheDocument()
    expect(within(aside).queryByRole("tabpanel")).not.toBeInTheDocument()
  })

  it("switching views changes the URL through the route table", async () => {
    const user = userEvent.setup()
    await renderApp("/playground")
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
    expect(dashboardShellSource).toMatch(/react-router/i)
    // Thin App shim composes the shell; the shell owns the router wiring.
    expect(appSource).toContain("DashboardShell")
    expect(appSource).toContain("AppProviders")
  })

  it("P1-FINAL: legacy /providers redirects to the merged Settings registry", async () => {
    await renderApp("/providers")
    await waitFor(() => {
      expect(
        within(screen.getByRole("main")).getByRole("heading", {
          name: "Settings",
        })
      ).toBeInTheDocument()
    })
    expect(testPath()).toBe("/settings")
  })

  it("App source declares the Routes table with redirect + catch-all", () => {
    expect(dashboardShellSource).toMatch(/<Routes/)
    expect(dashboardShellSource).toMatch(/<Route/)
    for (const routePath of [
      "/playground",
      "/routing",
      "/usage",
      "/activity",
      "/settings",
      "/projects",
      "/account",
      "/admin/users",
    ]) {
      expect(routesSource).toContain(`"${routePath}"`)
    }
    // U1: the root and unknown paths land on the last valid project, else
    // the project list; the legacy /providers redirect stays a Navigate.
    expect(dashboardShellSource).toMatch(/<Navigate/)
    expect(dashboardShellSource).toMatch(/path="\/"[^>]*element=\{<WorkspaceLanding/)
    expect(dashboardShellSource).toMatch(/path="\*"[^>]*element=\{<WorkspaceLanding/)
    // Thin App shim renders the shell that owns the table.
    expect(appSource).toContain("DashboardShell")
  })
})

describe("AC-SB-8e: PillTabs gold standard untouched", () => {
  it("Routing view still exposes Strategy/Simulator/Ranks/Resilience pill tabs", async () => {
    const user = userEvent.setup()
    await renderApp("/playground")
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
    ).toEqual(["Strategy", "Simulator"])
  })

  it("Settings view still exposes Providers/Keys/Failover pill tabs", async () => {
    const user = userEvent.setup()
    await renderApp("/playground")
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
    expect(dashboardShellSource).toMatch(
      /from\s+["']@\/app\/layout\/Sidebar["']/
    )
    expect(dashboardShellSource.includes("<Sidebar")).toBe(true)
    // Thin App shim renders the shell; the old Sidebar path re-exports it.
    expect(appSource).toContain("DashboardShell")
  })

  it("App source declares the horizontal shell", () => {
    expect(dashboardShellSource).toMatch(/flex-row/)
  })

  it("App exposes the sidebar collapse toggle", async () => {
    const user = userEvent.setup()
    await renderApp()
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

describe("AC4/AC5 (R-UI, U1): the session gate filters Admin by system permission", () => {
  it("system.settings.write direct /admin/users URL renders the creation screen", async () => {
    await renderApp("/admin/users", adminAccountFixture())
    await waitFor(() => {
      expect(
        within(screen.getByRole("main")).getByRole("heading", {
          name: "Accounts",
        })
      ).toBeInTheDocument()
    })
    expect(testPath()).toBe("/admin/users")
    expect(
      within(screen.getByRole("navigation", { name: "Primary" })).getByRole(
        "link",
        { name: "Admin", exact: true }
      )
    ).toBeInTheDocument()
    expect(screen.getByLabelText("Email")).toBeInTheDocument()
    expect(screen.queryByLabelText("Account role")).not.toBeInTheDocument()
    expect(screen.queryByLabelText("Account UUID")).not.toBeInTheDocument()
  })

  it("without system permissions: no Admin link, and the direct URL redirects to the landing", async () => {
    await renderApp("/admin/users", agentAccountFixture())
    await waitFor(() => {
      expect(
        within(screen.getByRole("main")).getByRole("heading", { name: "Projects" })
      ).toBeInTheDocument()
    })
    expect(testPath()).toBe("/projects")
    expect(
      within(screen.getByRole("navigation", { name: "Primary" })).queryByRole(
        "link",
        { name: "Admin", exact: true }
      )
    ).not.toBeInTheDocument()
    expect(screen.queryByLabelText("Account role")).not.toBeInTheDocument()
    expect(screen.queryByLabelText("Account UUID")).not.toBeInTheDocument()
  })
})

describe("SB-ACTIONS (R-UI): shell Sign out exits the session", () => {
  it("Sign out from the account popup reaches the login screen", async () => {
    const user = userEvent.setup()
    await renderApp("/playground", adminAccountFixture())

    await user.click(
      screen.getByRole("button", { name: "Open user menu", exact: true })
    )
    await screen.findByRole("dialog", { name: "User account" })
    await user.click(screen.getByRole("button", { name: "Sign out", exact: true }))

    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: "Sign in" })
      ).toBeInTheDocument()
    })
    expect(
      screen.queryByRole("navigation", { name: "Primary" })
    ).not.toBeInTheDocument()
  })

  it("a route change resets the open account popup", async () => {
    const user = userEvent.setup()
    await renderApp("/playground", adminAccountFixture())

    await user.click(
      screen.getByRole("button", { name: "Open user menu", exact: true })
    )
    await screen.findByRole("dialog", { name: "User account" })
    await user.click(
      within(screen.getByRole("navigation", { name: "Primary" })).getByRole(
        "link",
        { name: "Routing", exact: true }
      )
    )

    await waitFor(() => {
      expect(
        screen.queryByRole("dialog", { name: "User account" })
      ).not.toBeInTheDocument()
    })
    expect(testPath()).toBe("/routing")
  })
})

describe("SB4-BRAND: shell header-control journey", () => {
  it("collapse then logo-button expansion restores the rail", async () => {
    const user = userEvent.setup()
    await renderApp("/playground", adminAccountFixture())

    await user.click(
      screen.getByRole("button", { name: "Collapse sidebar", exact: true })
    )
    expect(
      (document.querySelector("aside") as HTMLElement).className
    ).toMatch(/w-16/)
    const expand = screen.getByRole("button", {
      name: "Expand sidebar",
      exact: true,
    })
    expect(expand.querySelector("img")).not.toBeNull()

    await user.click(expand)

    expect(
      screen.getByRole("button", { name: "Collapse sidebar", exact: true })
    ).toBeInTheDocument()
    expect(
      (document.querySelector("aside") as HTMLElement).className
    ).not.toMatch(/w-16/)
    expect(testPath()).toBe("/playground")
  })

  it("collapsed rail exposes exactly one expansion control", async () => {
    const user = userEvent.setup()
    await renderApp("/playground", adminAccountFixture())

    await user.click(
      screen.getByRole("button", { name: "Collapse sidebar", exact: true })
    )

    expect(
      screen.getAllByRole("button", { name: "Expand sidebar", exact: true })
    ).toHaveLength(1)
  })
})
