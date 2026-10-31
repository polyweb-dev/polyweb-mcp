import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { err, installFetchStub, ok } from "@/test/fetchMock"
import { ProjectsProvider, ProjectScopeProvider } from "@/domains/projects"
import { ProjectOverviewPage } from "./ProjectOverviewPage"

const PROJECT = { id: "p1", account_id: "a", name: "Alpha", slug: "alpha", status: "active", created_by: "u", created_at: "t", version: 1 }

function renderPage(permissions: string[] = ["project.read", "members.read"]) {
  installFetchStub((req) => {
    if (req.url === "/api/v1/system/access") return ok({ rollout_state: "preview", permissions: [] })
    if (req.url === "/api/v1/projects?include_archived=true") return ok([PROJECT])
    if (req.url === "/api/v1/projects/p1/access") {
      return ok({ project_id: "p1", permissions, roles: ["project_member", "routing_editor"], policy_revision: 2 })
    }
    return err(404, null)
  })
  return render(
    <MemoryRouter>
      <ProjectsProvider accountId="acc">
        <ProjectScopeProvider accountId="acc" projectId="p1">
          <ProjectOverviewPage />
        </ProjectScopeProvider>
      </ProjectsProvider>
    </MemoryRouter>
  )
}

describe("ProjectOverviewPage", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("shows the project name, status, and role labels without execution data", async () => {
    renderPage()
    await screen.findByRole("heading", { name: "Alpha" })
    expect(screen.getByText("Status: Active")).toBeInTheDocument()
    expect(screen.getByText("Project member")).toBeInTheDocument()
    expect(screen.getByText("Routing editor")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Members" })).toBeInTheDocument()
    expect(screen.getByText(/not available in this preview/)).toBeInTheDocument()
    expect(screen.queryByText(/results|queries/i)).toBeNull()
  })

  it("hides the Members link without members.read", async () => {
    renderPage(["project.read"])
    await screen.findByRole("heading", { name: "Alpha" })
    expect(screen.queryByRole("link", { name: "Members" })).toBeNull()
  })
})
