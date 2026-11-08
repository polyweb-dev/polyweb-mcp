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
  PROJECT_ADMIN_PERMISSIONS,
  PROJECT_ALPHA_ID,
  answerWorkspaceAccess,
  personaSystemPermissions,
  projectFixture,
} from "@/test/accessFixtures"
import { answerProjectProviders } from "@/test/projectPlayground"
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
 * page is retired into the System Providers page — no /providers view;
 * legacy /providers and /settings redirect to /system/providers, /usage to
 * /system/quotas. System credentials and capacity redirect to the account vault.
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
 *   C4-6  Playground PillTabs switching leaves the location path unchanged.
 *   C4-7  no regression: flex-row shell, provider views, PillTabs gold
 *         standard.
 */

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="test-location">{`${location.pathname}${location.search}`}</div>
}

async function renderAt(route: string, account: UserAccount = adminAccountFixture()) {
  installImmediateLocks()
  installFakeChannel()
  const backendHandler: FetchHandler = (req) => {
    const access = answerWorkspaceAccess(req, {
      systemPermissions: account.id === adminAccountFixture().id
        ? [...personaSystemPermissions(account), "vault.manage"]
        : personaSystemPermissions(account),
      projects: [projectFixture()],
      projectPermissions: { [PROJECT_ALPHA_ID]: PROJECT_ADMIN_PERMISSIONS },
    })
    if (access !== null) return access
    const projectView = answerProjectProviders(req)
    if (projectView !== null) return projectView
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
  { link: "Providers", heading: "Providers", path: "/system/providers" },
  { link: "Quotas", heading: "Quotas", path: "/system/quotas" },
  { link: "Projects", heading: "Projects", path: "/projects" },
  { link: "Keys and pools", heading: "Keys and pools", path: "/account/keys" },
  { link: "Account", heading: "Account", path: "/account" },
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
    await renderAt("/account")
    await expectView("Account", "Account", "/account")
    await followLink("Quotas")
    await expectView("Quotas", "Quotas", "/system/quotas")
  })

  it("every sidebar link advertises its exact route href", async () => {
    await renderAt("/account")
    const nav = screen.getByRole("navigation", { name: "Primary" })
    for (const { link, path } of ROUTE_TABLE) {
      expect(
        within(nav).getByRole("link", { name: link, exact: true })
      ).toHaveAttribute("href", path)
    }
  })
})

describe("C4-2: route table + / redirect + catch-all", () => {
  it("root path lands on /projects when no last project is remembered", async () => {
    await renderAt("/")
    await expectView("Projects", "Projects", "/projects")
  })

  it("unknown paths fall back to the project-first landing", async () => {
    await renderAt("/no-such-view")
    await expectView("Projects", "Projects", "/projects")
  })

  it("legacy /providers redirects to the System Providers page", async () => {
    await renderAt("/providers")
    // Redirect plus Providers registry render under full-suite parallel load:
    // budget above the default 1000ms (assertion unchanged).
    await waitFor(
      () => {
        expect(within(screen.getByRole("main")).getByRole("heading", { name: "Providers" })).toBeInTheDocument()
      },
      { timeout: 5000 }
    )
    expect(testPath()).toBe("/system/providers")
  })

  it("there is no /quotas route — quotas renders at /system/quotas", async () => {
    await renderAt("/quotas")
    await expectView("Projects", "Projects", "/projects")
    expect(within(screen.getByRole("main")).queryByRole("heading", { name: "Quotas" })).toBeNull()
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

  it("deep-link /system/credentials redirects to Keys and pools", async () => {
    await renderAt("/system/credentials")
    await expectView("Keys and pools", "Keys and pools", "/account/keys")
    expect(within(screen.getByRole("main")).queryByRole("tablist")).not.toBeInTheDocument()
    expect(await screen.findByRole("button", { name: "Add key" })).toBeInTheDocument()
    expect(
      within(screen.getByRole("navigation", { name: "Primary" })).queryByRole("link", { name: "System credentials" })
    ).not.toBeInTheDocument()
  })
})

describe("C4-4: navigation restores view + exactly one current marker", () => {
  it("sequential navigation keeps view, URL, and marker in sync", async () => {
    await renderAt("/system/providers")
    await expectView("Providers", "Providers", "/system/providers")
    await followLink("Quotas")
    await expectView("Quotas", "Quotas", "/system/quotas")
    await followLink("Providers")
    await expectView("Providers", "Providers", "/system/providers")
  })
})

describe("C4-5: sidebar active sync, collapse/drawer/persistence preserved", () => {
  it("exactly one link is current after every navigation", async () => {
    await renderAt("/account")
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
    await renderAt("/system/quotas")
    await expectView("Quotas", "Quotas", "/system/quotas")
    await user.click(
      screen.getByRole("button", { name: "Collapse sidebar", exact: true })
    )
    expect((document.querySelector("aside") as HTMLElement).className).toMatch(
      /w-16/
    )
    expect(testPath()).toBe("/system/quotas")
    expect(
      within(screen.getByRole("navigation", { name: "Primary" })).getByRole(
        "link",
        { name: "Quotas", exact: true }
      )
    ).toHaveAttribute("aria-current", "page")
  })

  it("selecting a drawer item navigates and closes the drawer", async () => {
    const user = userEvent.setup()
    await renderAt("/account")
    await expectView("Account", "Account", "/account")
    await user.click(
      screen.getByRole("button", { name: "Open navigation", exact: true })
    )
    expect(screen.getByRole("dialog")).toBeInTheDocument()
    await user.click(
      within(screen.getByRole("dialog")).getByRole("link", {
        name: "Quotas",
        exact: true,
      })
    )
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    await expectView("Quotas", "Quotas", "/system/quotas")
  })

  it("collapse persistence key survives the router migration", async () => {
    const user = userEvent.setup()
    await renderAt("/account")
    await user.click(
      screen.getByRole("button", { name: "Collapse sidebar", exact: true })
    )
    expect(window.localStorage.getItem("freesearch.sidebar.collapsed")).toBe("1")
    expect(testPath()).toBe("/account")
  })
})

describe("C4-6: PillTabs switching leaves the URL path unchanged", () => {
  it("redirects the former Providers keys query to the vault", async () => {
    await renderAt("/system/providers?tab=keys")
    await expectView("Keys and pools", "Keys and pools", "/account/keys")
    expect(within(screen.getByRole("main")).queryByRole("tablist")).not.toBeInTheDocument()
  })

  it("Playground Search/Fetch tabs switch without pushing history", async () => {
    const user = userEvent.setup()
    const playgroundPath = `/p/${PROJECT_ALPHA_ID}/playground`
    await renderAt(playgroundPath)
    await waitFor(() => {
      expect(
        within(screen.getByRole("main")).getByRole("heading", { name: "Playground" })
      ).toBeInTheDocument()
    })
    expect(
      within(screen.getByRole("navigation", { name: "Project" })).getByRole("link", {
        name: "Playground",
        exact: true,
      })
    ).toHaveAttribute("aria-current", "page")
    await user.click(screen.getByRole("tab", { name: "Fetch", exact: true }))
    expect(testPath()).toBe(playgroundPath)
    await user.click(screen.getByRole("tab", { name: "Search", exact: true }))
    expect(testPath()).toBe(playgroundPath)
  })
})

describe("C4-7: no regression — shell, providers, views", () => {
  it("shell keeps the flex-row aside+main layout with no header", async () => {
    await renderAt("/routing")
    const aside = document.querySelector("aside")
    expect(aside).not.toBeNull()
    expect((aside!.parentElement as HTMLElement).className).toMatch(/flex-row/)
    expect(screen.getByRole("main")).toBeInTheDocument()
    expect(document.querySelector("header")).toBeNull()
  })

  it("legacy /providers URL redirects into the System Providers registry", async () => {
    await renderAt("/providers")
    // Redirect plus Providers registry render under full-suite parallel load:
    // budget above the default 1000ms (assertion unchanged).
    await waitFor(
      () => {
        expect(within(screen.getByRole("main")).getByRole("heading", { name: "Providers" })).toBeInTheDocument()
      },
      { timeout: 5000 },
    )
    await expectView("Providers", "Providers", "/system/providers")
    await waitFor(() => {
      expect(screen.getByText("Brave Search")).toBeInTheDocument()
    })
  })

  it("Providers retains its catalog without a legacy tab list", async () => {
    await renderAt("/system/providers")
    await expectView("Providers", "Providers", "/system/providers")
    expect(within(screen.getByRole("main")).queryByRole("tablist")).not.toBeInTheDocument()
    expect(await screen.findByText("Brave Search")).toBeInTheDocument()
  })
})

describe("Retired Accounts route", () => {
  it("redirects the old URL for a system administrator", async () => {
    await renderAt("/admin/users", adminAccountFixture())
    await expectView("Projects", "Projects", "/projects")
    expect(screen.queryByRole("button", { name: "New account" })).not.toBeInTheDocument()
    expect(screen.queryByLabelText("Account role")).not.toBeInTheDocument()
    expect(screen.queryByLabelText("Account UUID")).not.toBeInTheDocument()
  })

  it("a caller without system permissions sees no Accounts link", async () => {
    await renderAt("/account", agentAccountFixture())
    expect(
      within(screen.getByRole("navigation", { name: "Primary" })).queryByRole(
        "link",
        { name: "Accounts", exact: true }
      )
    ).not.toBeInTheDocument()
  })

  it("a direct /admin/users URL without system.settings.write redirects to the landing", async () => {
    await renderAt("/admin/users", agentAccountFixture())
    await expectView("Projects", "Projects", "/projects")
    expect(screen.queryByLabelText("Account role")).not.toBeInTheDocument()
    expect(screen.queryByLabelText("Account UUID")).not.toBeInTheDocument()
  })
})
