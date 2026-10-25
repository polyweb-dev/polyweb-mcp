import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router"
import { err, installFetchStub, ok } from "@/test/fetchMock"
import { ProjectsProvider, ProjectScopeProvider } from "@/domains/projects"
import { ProjectScopeGate } from "./ProjectScopeGate"

function renderGate(access: () => number) {
  const stub = installFetchStub((req) => {
    if (req.url === "/api/v1/system/access") {
      return ok({ rollout_state: "preview", permissions: [] })
    }
    if (req.url === "/api/v1/projects?include_archived=true") return ok([])
    if (req.url === "/api/v1/projects/p1/access") {
      const status = access()
      return status === 200
        ? ok({ project_id: "p1", permissions: [], roles: [], policy_revision: 1 })
        : err(status, null)
    }
    if (req.url === "/api/v1/projects/p1/members") return ok([])
    return err(404, null)
  })
  render(
    <MemoryRouter>
      <ProjectsProvider accountId="acc">
        <ProjectScopeProvider accountId="acc" projectId="p1">
          <ProjectScopeGate>
            <div>project content</div>
          </ProjectScopeGate>
        </ProjectScopeProvider>
      </ProjectsProvider>
    </MemoryRouter>
  )
  return stub
}

describe("ProjectScopeGate", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("renders the unavailable view on a 404 access read", async () => {
    renderGate(() => 404)
    await screen.findByText("Project unavailable")
    expect(
      screen.getByText("You do not have access to this project, or it does not exist.")
    ).toBeInTheDocument()
    expect(screen.queryByText("project content")).toBeNull()
  })

  it("renders a retry view on a transient access failure", async () => {
    renderGate(() => 503)
    await screen.findByText("The project could not be loaded.")
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument()
    expect(screen.queryByText("Project unavailable")).toBeNull()
    expect(screen.queryByText("project content")).toBeNull()
  })

  it("re-loads the access descriptor and recovers on retry", async () => {
    let status = 503
    renderGate(() => status)
    await screen.findByText("The project could not be loaded.")
    status = 200
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Retry" }))
    await screen.findByText("project content")
  })
})
