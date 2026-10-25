import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter, Route, Routes, useLocation } from "react-router"
import { err, installFetchStub, ok } from "@/test/fetchMock"
import { ProjectsProvider } from "@/domains/projects"
import { ProjectWorkspace } from "./ProjectWorkspace"
import { AuthContext } from "@/domains/auth/state/context"
import { authenticatedContextValue } from "@/test/renderAuthenticated"
import { adminAccountFixture } from "@/test/authFixtures"

const PROJECT = { id: "11111111-1111-4111-8111-111111111111", account_id: "a", name: "Alpha", slug: "alpha", status: "active", created_by: "u", created_at: "t", version: 1 }

function PathProbe() {
  const { pathname } = useLocation()
  return <div data-testid="path">{pathname}</div>
}

function renderWorkspace(route: string, accessStatus = 200) {
  const stub = installFetchStub((req) => {
    if (req.url === "/api/v1/system/access") return ok({ rollout_state: "preview", permissions: [] })
    if (req.url === "/api/v1/projects?include_archived=true") return ok([PROJECT])
    if (req.url === `/api/v1/projects/${PROJECT.id}/access`) {
      return accessStatus === 200
        ? ok({ project_id: PROJECT.id, permissions: ["project.read"], roles: ["project_member"], policy_revision: 1 })
        : err(accessStatus, null)
    }
    return err(404, null)
  })
  render(
    <MemoryRouter initialEntries={[route]}>
      <AuthContext.Provider value={authenticatedContextValue(adminAccountFixture())}>
        <ProjectsProvider accountId={adminAccountFixture().id}>
          <Routes>
            <Route path="/p/:projectId/*" element={<ProjectWorkspace />} />
            <Route path="*" element={<PathProbe />} />
          </Routes>
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
  })

  it("shows the unavailable view for an inaccessible project without member reads", async () => {
    const stub = renderWorkspace(`/p/${PROJECT.id}/members`, 404)
    await screen.findByText("Project unavailable")
    expect(screen.getByText("You do not have access to this project, or it does not exist.")).toBeInTheDocument()
    await waitFor(() => {
      expect(stub.requestsTo(`/api/v1/projects/${PROJECT.id}/members`)).toHaveLength(0)
    })
  })
})
