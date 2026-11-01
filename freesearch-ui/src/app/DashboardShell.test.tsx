import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, useLocation } from "react-router"
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
  return <div data-testid="location">{useLocation().pathname}</div>
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
  render(
    <MemoryRouter initialEntries={[route]}>
      <App />
      <LocationProbe />
    </MemoryRouter>
  )
  return stub
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

    expect(await screen.findByRole("heading", { level: 1, name: "API keys" })).toBeInTheDocument()
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
        "Members",
      ])
    )
    expect(screen.queryByRole("heading", { level: 1, name: "API keys" })).toBeNull()
  })
})

describe("DashboardShell former global sections", () => {
  it.each([
    ["/playground", "playground", "Search Playground"],
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

    expect(await screen.findByRole("heading", { name: "Search Playground" })).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Select project (current: Alpha)" }))
    await user.click(screen.getByRole("menuitem", { name: /Beta/ }))

    await waitFor(() => expect(location()).toBe(`/p/${PROJECT_BETA_ID}/playground`))
    expect(await screen.findByRole("heading", { name: "Search Playground" })).toBeInTheDocument()
  })
})

describe("DashboardShell access states", () => {
  it("shows the loading status on a gated route while system access loads", async () => {
    const gate = deferred<Response>()
    renderShell("/settings", adminAccountFixture(), (req) =>
      req.url === "/api/v1/system/access" ? gate.promise : answerWorkspaceAccess(req, ACCESS) ?? controlRoutes(req)
    )
    const status = await screen.findByText("Loading workspace…")
    expect(status).toHaveAttribute("role", "status")
    expect(location()).toBe("/settings")
    gate.resolve(ok(systemAccessFixture()))
    expect(await within(screen.getByRole("main")).findByRole("heading", { name: "Settings" })).toBeInTheDocument()
    expect(location()).toBe("/settings")
  })

  it("shows the failure alert with Retry and recovers on a successful retry", async () => {
    let fail = true
    const user = userEvent.setup()
    renderShell("/routing", adminAccountFixture(), (req) => {
      if (req.url === "/api/v1/system/access" && fail) return err(503, null)
      return answerWorkspaceAccess(req, ACCESS) ?? controlRoutes(req)
    })

    const alert = await screen.findByText("The workspace could not be loaded.")
    expect(alert.closest('[role="alert"]')).not.toBeNull()
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument()
    fail = false
    await user.click(screen.getByRole("button", { name: "Retry" }))
    expect(await within(screen.getByRole("main")).findByRole("heading", { name: "Routing" })).toBeInTheDocument()
  })

  it("redirects an unauthorized direct URL through the landing to the project list", async () => {
    renderWithAccess("/settings", { ...ACCESS, systemPermissions: [] }, agentAccountFixture())
    await waitFor(() => expect(location()).toBe("/projects"))
    expect(within(screen.getByRole("navigation", { name: "Primary" })).queryByRole("link", { name: "Settings" })).toBeNull()
  })
})
