import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter, Route, Routes, useLocation } from "react-router"
import { err, installFetchStub, ok } from "@/test/fetchMock"
import { ProjectScopeProvider, ProjectsProvider } from "@/domains/projects"
import { ProjectWorkspace } from "./ProjectWorkspace"
import { projectIdFromPath } from "./routes"
import { AuthContext } from "@/domains/auth/state/context"
import { authenticatedContextValue } from "@/test/renderAuthenticated"
import { adminAccountFixture } from "@/test/authFixtures"
import { PROJECT_ADMIN_PERMISSIONS, PROJECT_MEMBER_PERMISSIONS } from "@/test/accessFixtures"
import { NotificationsProvider } from "@/shared/notifications/NotificationsContext"

const PROJECT = { id: "11111111-1111-4111-8111-111111111111", account_id: "a", name: "Alpha", slug: "alpha", status: "active", created_by: "u", created_at: "t", version: 1 }

function PathProbe() {
  const { pathname } = useLocation()
  return <div data-testid="path">{pathname}</div>
}

/** Mirror of the shell: the project scope keyed by the URL project id. */
function ScopedWorkspace() {
  const { pathname } = useLocation()
  const accountId = adminAccountFixture().id
  return (
    <ProjectScopeProvider accountId={accountId} projectId={projectIdFromPath(pathname)}>
      <ProjectWorkspace accountId={accountId} />
      <PathProbe />
    </ProjectScopeProvider>
  )
}

function renderWorkspace(route: string, accessStatus = 200, permissions: readonly string[] = ["project.read"]) {
  const stub = installFetchStub((req) => {
    if (req.url === "/api/v1/system/access") return ok({ rollout_state: "preview", permissions: [] })
    if (req.url === "/api/v1/projects?include_archived=true") return ok([PROJECT])
    if (req.url === `/api/v1/projects/${PROJECT.id}/access`) {
      return accessStatus === 200
        ? ok({ project_id: PROJECT.id, permissions, roles: ["project_member"], policy_revision: 1 })
        : err(accessStatus, null)
    }
    if (req.url === `/api/v1/projects/${PROJECT.id}/members`) return ok([])
    if (req.url === `/api/v1/projects/${PROJECT.id}/api-keys`) return ok([])
    if (req.url.startsWith(`/api/v1/projects/${PROJECT.id}/traces`)) {
      return ok({ items: [], generated_at: "2026-10-30T10:00:00Z", next_cursor: null })
    }
    if (req.url === `/api/v1/projects/${PROJECT.id}/providers`) {
      return ok({ project_id: PROJECT.id, providers: [], allocations: [] })
    }
    if (req.url === `/api/v1/projects/${PROJECT.id}/credentials`) return ok([])
    if (req.url === `/api/v1/projects/${PROJECT.id}/settings`) {
      return ok({ namespace: "settings", fields: {}, effective_settings: {}, provenance_by_field: {}, system_revision: 1, project_revision: 0 })
    }
    if (/\/(usage|dashboard)(\?|$)/.test(req.url)) {
      return ok({ project_id: PROJECT.id, totals: [], recent_usage: [], generated_at: "x" })
    }
    return err(404, null)
  })
  render(
    <MemoryRouter initialEntries={[route]}>
      <AuthContext.Provider value={authenticatedContextValue(adminAccountFixture())}>
        <ProjectsProvider accountId={adminAccountFixture().id}>
          <NotificationsProvider>
            <Routes>
              <Route path="/p/:projectId/*" element={<ScopedWorkspace />} />
              <Route path="*" element={<PathProbe />} />
            </Routes>
          </NotificationsProvider>
        </ProjectsProvider>
      </AuthContext.Provider>
    </MemoryRouter>
  )
  return stub
}

describe("ProjectWorkspace", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("renders the overview and redirects account-scoped sections to it", async () => {
    renderWorkspace(`/p/${PROJECT.id}/usage`)
    await screen.findByRole("heading", { name: "Alpha" })
    expect(screen.queryByRole("heading", { name: /usage|activity|playground/i })).toBeNull()
    expect(screen.getByTestId("path").textContent).toBe(`/p/${PROJECT.id}`)
  })

  it("shows the unavailable view for an inaccessible project without member reads", async () => {
    const stub = renderWorkspace(`/p/${PROJECT.id}/members`, 404)
    await screen.findByText("Project unavailable")
    expect(screen.getByText("You do not have access to this project, or it does not exist.")).toBeInTheDocument()
    await waitFor(() => {
      expect(stub.requestsTo(`/api/v1/projects/${PROJECT.id}/members`)).toHaveLength(0)
    })
  })

  it("redirects a section whose permission is absent to the overview", async () => {
    const stub = renderWorkspace(`/p/${PROJECT.id}/api-keys`, 200, PROJECT_MEMBER_PERMISSIONS)
    await screen.findByRole("heading", { name: "Alpha" })
    expect(screen.getByTestId("path").textContent).toBe(`/p/${PROJECT.id}`)
    expect(stub.requestsTo(`/api/v1/projects/${PROJECT.id}/api-keys`)).toHaveLength(0)
  })

  it("renders the API keys section with tokens.manage", async () => {
    renderWorkspace(`/p/${PROJECT.id}/api-keys`, 200, PROJECT_ADMIN_PERMISSIONS)
    expect(await screen.findByRole("heading", { level: 1, name: "API keys" })).toBeInTheDocument()
    expect(screen.getByTestId("path").textContent).toBe(`/p/${PROJECT.id}/api-keys`)
  })

  it.each([
    ["playground", ["project.read", "fetch.execute"], "Search Playground"],
    ["activity", ["project.read", "traces.read"], "Activity"],
    ["usage", ["project.read", "usage.read"], "Usage"],
    ["providers", ["project.read", "providers.read"], "Providers"],
    ["settings", ["project.read", "settings.read"], "Settings"],
  ])("renders the %s section with its permission", async (segment, permissions, heading) => {
    renderWorkspace(`/p/${PROJECT.id}/${segment}`, 200, permissions)
    expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument()
    expect(screen.getByTestId("path").textContent).toBe(`/p/${PROJECT.id}/${segment}`)
  })

  it("shows the unavailable view for an overview without project.read", async () => {
    renderWorkspace(`/p/${PROJECT.id}`, 200, ["tokens.manage"])
    expect(await screen.findByText("Project unavailable")).toBeInTheDocument()
  })
})
