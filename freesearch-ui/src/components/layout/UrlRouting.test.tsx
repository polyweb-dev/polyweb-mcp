import React from "react"
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
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
} from "@/test/backendFixtures"

/**
 * C4 URL routing — route table over MemoryRouter (NEW, Red phase).
 *
 * Component-level contract for the approved plan:
 *   main.tsx BrowserRouter; App.tsx Routes table
 *   (/ /playground /routing /usage /activity /settings
 *   + /providers -> /settings redirect + * catch-all -> /playground;
 *   quotas maps to /usage, TabId unchanged, providers TabId retired);
 *   Sidebar NavLink (role link, aria-current preserved, drawer-close on
 *   navigate, active from router). PillTabs + views + persistence + theme
 *   untouched. freesearch-ui/ ONLY.
 *
 * P1-FINAL (blessed inversion, NOT a regression): the standalone Providers
 * page is retired into the Settings Providers tab — five workspace routes,
 * no /providers view, legacy /providers redirects to /settings.
 *
 * AC mapping:
 *   C4-1  router install + URL changes on nav (link click moves location).
 *   C4-2  route table + / redirect + catch-all to /playground.
 *   C4-3  deep-link initialEntries renders the exact heading.
 *   C4-4  sequential navigation restores view + exactly one aria-current
 *         (full browser back/forward + refresh are E2E-covered in
 *         tests/features/app-shell-routing.feature).
 *   C4-5  sidebar active sync (hrefs + aria-current), collapse/drawer/
 *         persistence preserved.
 *   C4-6  PillTabs switching (Routing, Settings, Playground) leaves the
 *         location unchanged.
 *   C4-7  no regression: flex-row shell, provider views, PillTabs gold
 *         standard.
 */

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="test-location">{location.pathname}</div>
}

async function renderAt(route: string, account: UserAccount = adminAccountFixture()) {
  installImmediateLocks()
  installFakeChannel()
  const backendHandler: FetchHandler = (req) => {
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
  return result
}

function testPath(): string {
  return screen.getByTestId("test-location").textContent ?? ""
}

async function followLink(label: string) {
  const user = userEvent.setup()
  await user.click(
    within(screen.getByRole("navigation", { name: "Primary" })).getByRole(
      "link",
      { name: label, exact: true }
    )
  )
}

async function expectView(label: string, heading: string, path: string) {
  await waitFor(() => {
    expect(
      within(screen.getByRole("main")).getByRole("heading", { name: heading })
    ).toBeInTheDocument()
  })
  expect(testPath()).toBe(path)
  expect(
    within(screen.getByRole("navigation", { name: "Primary" })).getByRole(
      "link",
      { name: label, exact: true }
    )
  ).toHaveAttribute("aria-current", "page")
  expect(
    document.querySelectorAll('aside [aria-current="page"]')
  ).toHaveLength(1)
}

const ROUTE_TABLE: Array<{ link: string; heading: string; path: string }> = [
  { link: "Playground", heading: "Search Playground", path: "/playground" },
  { link: "Routing", heading: "Routing", path: "/routing" },
  { link: "Usage", heading: "Usage", path: "/usage" },
  { link: "Activity", heading: "Activity", path: "/activity" },
  { link: "Settings", heading: "Settings", path: "/settings" },
  { link: "Account", heading: "Account", path: "/account" },
  { link: "Admin", heading: "Account roles", path: "/admin/users" },
]

beforeEach(() => {
  window.localStorage.clear()
})

afterEach(() => {
  removeLocks()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe("C4-1: router install + URL changes on nav", () => {
  it("clicking a sidebar link moves the router location and swaps the view", async () => {
    await renderAt("/playground")
    await expectView("Playground", "Search Playground", "/playground")
    await followLink("Routing")
    await expectView("Routing", "Routing", "/routing")
  })

  it("every sidebar link advertises its exact route href", async () => {
    await renderAt("/playground")
    const nav = screen.getByRole("navigation", { name: "Primary" })
    for (const { link, path } of ROUTE_TABLE) {
      expect(
        within(nav).getByRole("link", { name: link, exact: true })
      ).toHaveAttribute("href", path)
    }
  })
})

describe("C4-2: route table + / redirect + catch-all", () => {
  it("root path redirects to /playground", async () => {
    await renderAt("/")
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: "Search Playground" })
      ).toBeInTheDocument()
    })
    expect(testPath()).toBe("/playground")
  })

  it("unknown paths fall back to /playground", async () => {
    await renderAt("/no-such-view")
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: "Search Playground" })
      ).toBeInTheDocument()
    })
    expect(testPath()).toBe("/playground")
  })

  it("legacy /providers redirects to the merged Settings registry", async () => {
    await renderAt("/providers")
    // Redirect plus Settings registry render under full-suite parallel load:
    // budget above the default 1000ms (assertion unchanged).
    await waitFor(
      () => {
        expect(screen.getByRole("heading", { name: "Settings" })).toBeInTheDocument()
      },
      { timeout: 5000 }
    )
    expect(testPath()).toBe("/settings")
  })

  it("there is no /quotas route — quotas renders at /usage", async () => {
    await renderAt("/quotas")
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: "Search Playground" })
      ).toBeInTheDocument()
    })
    expect(testPath()).toBe("/playground")
  })
})

describe("C4-3: deep links render their view", () => {
  it.each(ROUTE_TABLE)(
    "deep-link $path renders the '$heading' view with '$link' current",
    async ({ link, heading, path }) => {
      await renderAt(path)
      await expectView(link, heading, path)
    }
  )
})

describe("C4-4: navigation restores view + exactly one current marker", () => {
  it("sequential navigation keeps view, URL, and marker in sync", async () => {
    await renderAt("/settings")
    await expectView("Settings", "Settings", "/settings")
    await followLink("Routing")
    await expectView("Routing", "Routing", "/routing")
    await followLink("Usage")
    await expectView("Usage", "Usage", "/usage")
    await followLink("Settings")
    await expectView("Settings", "Settings", "/settings")
  })
})

describe("C4-5: sidebar active sync, collapse/drawer/persistence preserved", () => {
  it("exactly one link is current after every navigation", async () => {
    await renderAt("/playground")
    for (const { link, heading, path } of ROUTE_TABLE) {
      await followLink(link)
      await waitFor(() => {
        expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument()
      })
      expect(testPath()).toBe(path)
      expect(
        document.querySelectorAll('aside [aria-current="page"]')
      ).toHaveLength(1)
      expect(
        within(screen.getByRole("navigation", { name: "Primary" })).getByRole(
          "link",
          { name: link, exact: true }
        )
      ).toHaveAttribute("aria-current", "page")
    }
  })

  it("collapse toggle still works without touching the URL", async () => {
    const user = userEvent.setup()
    await renderAt("/routing")
    await expectView("Routing", "Routing", "/routing")
    await user.click(
      screen.getByRole("button", { name: "Collapse sidebar", exact: true })
    )
    expect((document.querySelector("aside") as HTMLElement).className).toMatch(
      /w-16/
    )
    expect(testPath()).toBe("/routing")
    expect(
      within(screen.getByRole("navigation", { name: "Primary" })).getByRole(
        "link",
        { name: "Routing", exact: true }
      )
    ).toHaveAttribute("aria-current", "page")
  })

  it("selecting a drawer item navigates and closes the drawer", async () => {
    const user = userEvent.setup()
    await renderAt("/playground")
    await expectView("Playground", "Search Playground", "/playground")
    await user.click(
      screen.getByRole("button", { name: "Open navigation", exact: true })
    )
    expect(screen.getByRole("dialog")).toBeInTheDocument()
    await user.click(
      within(screen.getByRole("dialog")).getByRole("link", {
        name: "Activity",
        exact: true,
      })
    )
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    await expectView("Activity", "Activity", "/activity")
  })

  it("collapse persistence key survives the router migration", async () => {
    const user = userEvent.setup()
    await renderAt("/playground")
    await user.click(
      screen.getByRole("button", { name: "Collapse sidebar", exact: true })
    )
    expect(window.localStorage.getItem("freesearch.sidebar.collapsed")).toBe("1")
    expect(testPath()).toBe("/playground")
  })
})

describe("C4-6: PillTabs switching leaves the URL unchanged", () => {
  it("Routing pill tabs switch panels without pushing history", async () => {
    const user = userEvent.setup()
    await renderAt("/routing")
    await expectView("Routing", "Routing", "/routing")
    for (const tab of ["Simulator", "Ranks", "Resilience"]) {
      await user.click(screen.getByRole("tab", { name: tab, exact: true }))
      expect(testPath()).toBe("/routing")
    }
    await user.click(screen.getByRole("tab", { name: "Strategy", exact: true }))
    expect(testPath()).toBe("/routing")
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Routing" })).toBeInTheDocument()
    })
  })

  it("Settings pill tabs switch panels without pushing history", async () => {
    const user = userEvent.setup()
    await renderAt("/settings")
    await expectView("Settings", "Settings", "/settings")
    for (const tab of ["Keys", "Failover"]) {
      await user.click(screen.getByRole("tab", { name: tab, exact: true }))
      expect(testPath()).toBe("/settings")
    }
    await user.click(screen.getByRole("tab", { name: "Providers", exact: true }))
    expect(testPath()).toBe("/settings")
  })

  it("Playground Search/Fetch tabs switch without pushing history", async () => {
    const user = userEvent.setup()
    await renderAt("/playground")
    await expectView("Playground", "Search Playground", "/playground")
    await user.click(screen.getByRole("tab", { name: "Fetch", exact: true }))
    expect(testPath()).toBe("/playground")
    await user.click(screen.getByRole("tab", { name: "Search", exact: true }))
    expect(testPath()).toBe("/playground")
  })
})

describe("C4-7: no regression — shell, providers, views", () => {
  it("shell keeps the flex-row aside+main layout with no header", async () => {
    await renderAt("/playground")
    const aside = document.querySelector("aside")
    expect(aside).not.toBeNull()
    expect((aside!.parentElement as HTMLElement).className).toMatch(/flex-row/)
    expect(screen.getByRole("main")).toBeInTheDocument()
    expect(document.querySelector("header")).toBeNull()
  })

  it("legacy /providers URL redirects into the merged Settings registry", async () => {
    await renderAt("/providers")
    await expectView("Settings", "Settings", "/settings")
    await waitFor(() => {
      expect(screen.getByText("Brave Search")).toBeInTheDocument()
    })
  })

  it("Routing + Settings PillTabs gold standard is intact", async () => {
    await renderAt("/routing")
    await expectView("Routing", "Routing", "/routing")
    const routingPills = document.querySelector(
      '[data-slot="tabs-list"][data-variant="pill"]'
    )
    expect(routingPills).not.toBeNull()
    expect(
      within(routingPills as HTMLElement)
        .getAllByRole("tab")
        .map((t) => t.textContent)
    ).toEqual(["Strategy", "Simulator", "Ranks", "Resilience"])

    await followLink("Settings")
    await expectView("Settings", "Settings", "/settings")
    const settingsPills = within(screen.getByRole("main")).getByRole("tablist")
    expect(
      within(settingsPills as HTMLElement)
        .getAllByRole("tab")
        .map((t) => t.textContent)
    ).toEqual(["Providers", "Keys", "Failover"])
  })
})

describe("AC4/AC5 (R-UI): auth session gate filters Admin by role", () => {
  it("admin direct /admin/users URL renders the creation screen", async () => {
    await renderAt("/admin/users", adminAccountFixture())
    await expectView("Admin", "Account roles", "/admin/users")
    expect(screen.getByLabelText("Email")).toBeInTheDocument()
    expect(screen.getByLabelText("Account role")).toBeInTheDocument()
    expect(screen.queryByLabelText("Account UUID")).not.toBeInTheDocument()
  })

  it("agent sees no Admin link and direct /admin/users URL renders no creation form", async () => {
    await renderAt("/playground", agentAccountFixture())
    expect(
      within(screen.getByRole("navigation", { name: "Primary" })).queryByRole(
        "link",
        { name: "Admin", exact: true }
      )
    ).not.toBeInTheDocument()
  })

  it("agent direct /admin/users URL is rejected without the creation form", async () => {
    await renderAt("/admin/users", agentAccountFixture())
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: "Search Playground" })
      ).toBeInTheDocument()
    })
    expect(testPath()).toBe("/playground")
    expect(screen.queryByLabelText("Account role")).not.toBeInTheDocument()
    expect(screen.queryByLabelText("Account UUID")).not.toBeInTheDocument()
  })
})
