import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router"
import { err, installFetchStub, ok } from "@/test/fetchMock"
import { ProjectsProvider, ProjectScopeProvider } from "@/domains/projects"
import { projectStorageKey } from "@/domains/projects"
import { ProjectMembersPage } from "./ProjectMembersPage"

const MEMBER = { project_id: "p1", user_id: "u1", email: "admin@example.com", status: "active", roles: ["project_admin"], version: 1 }

function access(permissions: string[], roles = ["project_admin"]) {
  return { project_id: "p1", permissions, roles, policy_revision: 1 }
}

function renderPage(permissions: string[], members: unknown[] = [MEMBER]) {
  const stub = installFetchStub((req) => {
    if (req.url === "/api/v1/system/access") return ok({ rollout_state: "preview", permissions: [] })
    if (req.url === "/api/v1/projects?include_archived=true") return ok([])
    if (req.url === "/api/v1/projects/p1/access") return ok(access(permissions))
    if (req.url === "/api/v1/projects/p1/members" && req.method === "GET") return ok(members)
    return err(404, null)
  })
  render(
    <MemoryRouter>
      <ProjectsProvider accountId="acc">
        <ProjectScopeProvider accountId="acc" projectId="p1">
          <ProjectMembersPage accountId="acc" />
        </ProjectScopeProvider>
      </ProjectsProvider>
    </MemoryRouter>
  )
  return stub
}

describe("ProjectMembersPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.localStorage.clear()
  })

  it("shows the member table with emails and no controls for a read-only member", async () => {
    renderPage(["project.read", "members.read"])
    await screen.findByText("admin@example.com")
    expect(screen.getByText("Project admin")).toBeInTheDocument()
    expect(screen.queryByRole("form", { name: "Add member" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Suspend" })).toBeNull()
  })

  it("renders manage and role controls from effective permissions", async () => {
    renderPage(["members.read", "members.manage", "roles.assign"])
    await screen.findByText("admin@example.com")
    expect(screen.getByLabelText("Account email")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Suspend" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Remove" })).toBeInTheDocument()
    expect(screen.getByLabelText("Add role to admin@example.com")).toBeInTheDocument()
  })

  it("shows the last-admin message on the 409 conflict", async () => {
    installFetchStub((req) => {
      if (req.url === "/api/v1/system/access") return ok({ rollout_state: "preview", permissions: [] })
      if (req.url === "/api/v1/projects?include_archived=true") return ok([])
      if (req.url === "/api/v1/projects/p1/access") return ok(access(["members.read", "members.manage"]))
      if (req.url === "/api/v1/projects/p1/members" && req.method === "GET") return ok([MEMBER])
      if (req.method === "PATCH") return err(409, { detail: { code: "LAST_PROJECT_ADMIN", message: "x" } })
      return err(404, null)
    })
    render(
      <MemoryRouter>
        <ProjectsProvider accountId="acc">
          <ProjectScopeProvider accountId="acc" projectId="p1">
            <ProjectMembersPage accountId="acc" />
          </ProjectScopeProvider>
        </ProjectsProvider>
      </MemoryRouter>
    )
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "Suspend" }))
    await screen.findByText("A project must keep at least one active administrator.")
  })

  it("keeps the add draft under the project-scoped key", async () => {
    const keyA = projectStorageKey("member-draft", { accountId: "acc", projectId: "p1", schemaVersion: 1 })
    window.localStorage.setItem(keyA, JSON.stringify({ schemaVersion: 1, value: { email: "draft@a.io", role: "project_member" } }))
    renderPage(["members.read", "members.manage"])
    expect(await screen.findByLabelText("Account email")).toHaveValue("draft@a.io")
  })
})
