import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, useLocation, useNavigate } from "react-router"
import App from "@/App"
import { deferred, err, installAuthStub, ok } from "@/test/fetchMock"
import type { FetchHandler } from "@/test/fetchMock"
import { installFakeChannel, installImmediateLocks, removeLocks } from "@/test/browserStubs"
import { adminAccountFixture, agentAccountFixture } from "@/test/authFixtures"
import { allProvidersFixture, dashboardFixture, routingConfigFixture } from "@/test/backendFixtures"
import {
  PROJECT_ADMIN_PERMISSIONS,
  PROJECT_ALPHA_ID,
  PROJECT_BETA_ID,
  PROJECT_MEMBER_PERMISSIONS,
  SYSTEM_ADMIN_PERMISSIONS,
  answerWorkspaceAccess,
  projectFixture,
  systemAccessFixture,
} from "@/test/accessFixtures"
import type { WorkspaceAccessOptions } from "@/test/accessFixtures"
import type { UserAccount } from "@/domains/auth"
import { writeLastProject } from "@/domains/projects"

const ALPHA = projectFixture({ id: PROJECT_ALPHA_ID, name: "Alpha" })
const BETA = projectFixture({ id: PROJECT_BETA_ID, name: "Beta", slug: "beta" })

const ACCESS: WorkspaceAccessOptions = {
  projects: [ALPHA, BETA],
  projectPermissions: {
    [PROJECT_ALPHA_ID]: PROJECT_ADMIN_PERMISSIONS,
    [PROJECT_BETA_ID]: PROJECT_MEMBER_PERMISSIONS,
  },
}

function LocationProbe() {
  const { pathname, search } = useLocation()
  return <div data-testid="location">{`${pathname}${search}`}</div>
}

function BackProbe() {
  const navigate = useNavigate()
  return <button onClick={() => navigate(-1)}>Go back</button>
}

function RoutingNavigationProbe() {
  const navigate = useNavigate()
  return ["/routing", "/system/routing", `/p/${PROJECT_BETA_ID}/providers`].map((path) => (
    <button key={path} onClick={() => navigate(path)}>Visit {path}</button>
  ))
}

function controlRoutes(req: Parameters<FetchHandler>[0]): Response {
  if (req.url === "/api/v1/providers") return ok(allProvidersFixture())
  if (req.url === "/api/v1/routing/config") return ok(routingConfigFixture())
  if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
  if (/\/api\/v1\/projects\/[^/]+\/(members|api-keys)$/.test(req.url)) return ok([])
  const projectRead = /^\/api\/v1\/projects\/([^/]+)\/(providers|traces|usage|dashboard)/.exec(req.url)
  if (projectRead !== null) {
    const projectId = projectRead[1]
    if (projectRead[2] === "providers") return ok({ project_id: projectId, providers: [], allocations: [] })
    if (projectRead[2] === "traces") return ok({ items: [], generated_at: "2026-10-30T10:00:00Z", next_cursor: null })
    return ok({ project_id: projectId, totals: [], recent_usage: [], generated_at: "2026-10-30T10:00:00Z" })
  }
  return err(404, { detail: "unhandled test route" })
}

function renderShell(route: string, account: UserAccount, handler: FetchHandler) {
  installImmediateLocks()
  installFakeChannel()
  const stub = installAuthStub({ account }, handler)
  const view = render(
    <MemoryRouter initialEntries={[route]}>
      <App />
      <LocationProbe />
      <RoutingNavigationProbe />
    </MemoryRouter>
  )
  return { ...stub, unmount: view.unmount }
}

function renderWithAccess(route: string, options: WorkspaceAccessOptions = ACCESS, account = adminAccountFixture()) {
  return renderShell(route, account, (req) => answerWorkspaceAccess(req, options) ?? controlRoutes(req))
}

function location(): string {
  return screen.getByTestId("location").textContent ?? ""
}

beforeEach(() => window.localStorage.clear())

afterEach(() => {
  removeLocks()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe("DashboardShell project scope", () => {
  it("shows the selected project and the permitted sections above the global group", async () => {
    renderWithAccess(`/p/${PROJECT_ALPHA_ID}/members`)

    const projectNav = await screen.findByRole("navigation", { name: "Project" })
    await waitFor(() =>
      expect(within(projectNav).getAllByRole("link").map((link) => link.getAttribute("aria-label"))).toEqual([
        "Overview",
        "Playground",
        "Activity",
        "Usage",
        "Providers",
        "Settings",
        "Members",
        "API keys",
      ])
    )
    expect(screen.getByRole("button", { name: "Select project (current: Alpha)" })).toBeInTheDocument()
    expect(within(projectNav).getByRole("link", { name: "Members" })).toHaveAttribute("aria-current", "page")
    const primary = screen.getByRole("navigation", { name: "Primary" })
    expect(projectNav.compareDocumentPosition(primary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(await within(screen.getByRole("main")).findByRole("heading", { name: "Members" })).toBeInTheDocument()
  })

  it("shows no project group on a global route", async () => {
    renderWithAccess("/projects")
    await within(await screen.findByRole("main")).findByRole("heading", { name: "Projects" })
    expect(screen.queryByRole("navigation", { name: "Project" })).toBeNull()
  })

  it("never carries one project's access into another on a switch", async () => {
    const user = userEvent.setup()
    renderWithAccess(`/p/${PROJECT_ALPHA_ID}/api-keys`)

    expect(await screen.findByRole("heading", { name: "API keys" })).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Select project (current: Alpha)" }))
    await user.click(screen.getByRole("menuitem", { name: /Beta/ }))

    await waitFor(() => expect(location()).toBe(`/p/${PROJECT_BETA_ID}`))
    expect(await screen.findByRole("heading", { name: "Beta" })).toBeInTheDocument()
    const projectNav = screen.getByRole("navigation", { name: "Project" })
    await waitFor(() =>
      expect(within(projectNav).getAllByRole("link").map((link) => link.getAttribute("aria-label"))).toEqual([
        "Overview",
        "Playground",
        "Activity",
        "Usage",
        "Providers",
        "Settings",
        "Members",
      ])
    )
    expect(screen.queryByRole("heading", { name: "API keys" })).toBeNull()
  })
})

describe("DashboardShell former global sections", () => {
  it.each(["/routing", "/system/routing"])("remembers direct project visits for in-app navigation to %s", async (path) => {
    renderWithAccess(`/p/${PROJECT_ALPHA_ID}/providers`)
    await within(await screen.findByRole("main")).findByRole("heading", { name: "Providers" })
    await userEvent.click(screen.getByRole("button", { name: `Visit /p/${PROJECT_BETA_ID}/providers` }))
    await screen.findByRole("button", { name: "Select project (current: Beta)" })
    await within(screen.getByRole("main")).findByRole("heading", { name: "Providers" })
    await userEvent.click(screen.getByRole("button", { name: `Visit ${path}` }))

    await waitFor(() => expect(location()).toBe(`/p/${PROJECT_BETA_ID}/providers`))
    expect(await within(screen.getByRole("main")).findByRole("heading", { name: "Providers" })).toBeInTheDocument()
  })

  it.each(["/routing", "/system/routing"])("remembers a direct project visit across a fresh app load at %s", async (path) => {
    const view = renderWithAccess(`/p/${PROJECT_ALPHA_ID}/providers`)
    await within(await screen.findByRole("main")).findByRole("heading", { name: "Providers" })
    view.unmount()
    renderWithAccess(path)

    await waitFor(() => expect(location()).toBe(`/p/${PROJECT_ALPHA_ID}/providers`))
    expect(await within(screen.getByRole("main")).findByRole("heading", { name: "Providers" })).toBeInTheDocument()
  })

  it.each(["/routing", "/system/routing"])("redirects %s to the last readable project's Providers", async (path) => {
    writeLastProject(adminAccountFixture().id, PROJECT_ALPHA_ID)
    renderWithAccess(path)

    await waitFor(() => expect(location()).toBe(`/p/${PROJECT_ALPHA_ID}/providers`))
    expect(await within(screen.getByRole("main")).findByRole("heading", { name: "Providers" })).toBeInTheDocument()
    expect(within(screen.getByRole("navigation", { name: "Primary" })).queryByRole("link", { name: "Routing" })).toBeNull()
  })

  it.each(["/routing", "/system/routing"])("redirects %s to Projects without a remembered project", async (path) => {
    renderWithAccess(path)
    await waitFor(() => expect(location()).toBe("/projects"))
  })

  it("redirects Routing to Projects when the remembered project is no longer readable", async () => {
    writeLastProject(adminAccountFixture().id, PROJECT_BETA_ID)
    renderWithAccess("/routing", { ...ACCESS, projects: [ALPHA] })
    await waitFor(() => expect(location()).toBe("/projects"))
  })

  it("replaces the retired Routing URL in browser history", async () => {
    writeLastProject(adminAccountFixture().id, PROJECT_ALPHA_ID)
    installImmediateLocks()
    installFakeChannel()
    installAuthStub({ account: adminAccountFixture() }, (req) => answerWorkspaceAccess(req, ACCESS) ?? controlRoutes(req))
    render(
      <MemoryRouter initialEntries={["/account", "/routing"]}>
        <App />
        <LocationProbe />
        <BackProbe />
      </MemoryRouter>
    )

    await waitFor(() => expect(location()).toBe(`/p/${PROJECT_ALPHA_ID}/providers`))
    await userEvent.click(screen.getByRole("button", { name: "Go back" }))
    await waitFor(() => expect(location()).toBe("/account"))
  })

  it("redirects the retired Accounts URL to the last readable project", async () => {
    writeLastProject(adminAccountFixture().id, PROJECT_BETA_ID)
    renderWithAccess("/admin/users")

    await waitFor(() => expect(location()).toBe(`/p/${PROJECT_BETA_ID}`))
    expect(await within(screen.getByRole("main")).findByRole("heading", { name: "Beta" })).toBeInTheDocument()
  })

  it("redirects the retired Accounts URL to Projects without a remembered project", async () => {
    renderWithAccess("/admin/users")
    await waitFor(() => expect(location()).toBe("/projects"))
  })

  it.each([
    ["/playground", "playground", "Playground"],
    ["/activity", "activity", "Activity"],
  ])("redirects %s to the same section of the last project", async (path, segment, heading) => {
    writeLastProject(adminAccountFixture().id, PROJECT_BETA_ID)
    renderWithAccess(path)

    await waitFor(() => expect(location()).toBe(`/p/${PROJECT_BETA_ID}/${segment}`))
    expect(await within(screen.getByRole("main")).findByRole("heading", { name: heading })).toBeInTheDocument()
  })

  it.each(["/playground", "/activity"])("redirects %s to the project list without a last project", async (path) => {
    renderWithAccess(path)
    await waitFor(() => expect(location()).toBe("/projects"))
  })

  it("keeps the project section on a project switch from the playground", async () => {
    const user = userEvent.setup()
    renderWithAccess(`/p/${PROJECT_ALPHA_ID}/playground`)

    expect(await screen.findByRole("heading", { name: "Playground" })).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Select project (current: Alpha)" }))
    await user.click(screen.getByRole("menuitem", { name: /Beta/ }))

    await waitFor(() => expect(location()).toBe(`/p/${PROJECT_BETA_ID}/playground`))
    expect(await screen.findByRole("heading", { name: "Playground" })).toBeInTheDocument()
  })
})

describe("DashboardShell access states", () => {
  it("shows the loading status on a gated route while system access loads", async () => {
    const gate = deferred<Response>()
    renderShell("/system/providers", adminAccountFixture(), (req) =>
      req.url === "/api/v1/system/access" ? gate.promise : answerWorkspaceAccess(req, ACCESS) ?? controlRoutes(req)
    )
    const status = await screen.findByText("Loading workspace…")
    expect(status).toHaveAttribute("role", "status")
    expect(location()).toBe("/system/providers")
    gate.resolve(ok(systemAccessFixture()))
    expect(await within(screen.getByRole("main")).findByRole("heading", { name: "Providers" })).toBeInTheDocument()
    expect(location()).toBe("/system/providers")
  })

  it("shows the failure alert with Retry and recovers on a successful retry", async () => {
    let fail = true
    const user = userEvent.setup()
    renderShell("/system/quotas", adminAccountFixture(), (req) => {
      if (req.url === "/api/v1/system/access" && fail) return err(503, null)
      return answerWorkspaceAccess(req, ACCESS) ?? controlRoutes(req)
    })

    const alert = await screen.findByText("The workspace could not be loaded.")
    expect(alert.closest('[role="alert"]')).not.toBeNull()
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument()
    fail = false
    await user.click(screen.getByRole("button", { name: "Retry" }))
    expect(await within(screen.getByRole("main")).findByRole("heading", { name: "Quotas" })).toBeInTheDocument()
  })

  it.each([
    ["/system/credentials", "Keys and pools", "/account/keys"],
    ["/system/capacity", "Keys and pools", "/account/keys"],
    ["/system/keys", "Keys and pools", "/account/keys"],
    ["/settings?tab=keys", "Keys and pools", "/account/keys"],
    ["/providers?tab=keys", "Keys and pools", "/account/keys"],
    ["/system/providers?other=1&tab=keys", "Keys and pools", "/account/keys"],
    ["/system/providers?tab=credentials", "Keys and pools", "/account/keys"],
  ])("opens %s for the system administrator", async (path, heading, landed) => {
    renderWithAccess(path, { ...ACCESS, systemPermissions: [...SYSTEM_ADMIN_PERMISSIONS, "vault.manage"] })
    expect(await within(await screen.findByRole("main")).findByRole("heading", { name: heading })).toBeInTheDocument()
    await waitFor(() => expect(location()).toBe(landed))
  })

  it("denies the vault with allocation management alone", async () => {
    renderWithAccess("/system/credentials", { ...ACCESS, systemPermissions: ["system.allocations.manage"] }, agentAccountFixture())
    await waitFor(() => expect(location()).toBe("/projects"))
    const primary = screen.getByRole("navigation", { name: "Primary" })
    expect(within(primary).queryByRole("link", { name: "Capacity" })).toBeNull()
    expect(within(primary).queryByRole("link", { name: "Providers" })).toBeNull()
  })

  it("redirects an unauthorized direct URL through the landing to the project list", async () => {
    renderWithAccess("/settings", { ...ACCESS, systemPermissions: [] }, agentAccountFixture())
    await waitFor(() => expect(location()).toBe("/projects"))
    expect(within(screen.getByRole("navigation", { name: "Primary" })).queryByRole("link", { name: "Providers" })).toBeNull()
  })
})
