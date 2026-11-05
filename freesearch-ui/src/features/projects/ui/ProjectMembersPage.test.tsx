import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
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
    expect(screen.queryByRole("button", { name: /Actions for / })).toBeNull()
  })

  it("renders manage and role controls from effective permissions", async () => {
    renderPage(["members.read", "members.manage", "roles.assign"])
    await screen.findByText("admin@example.com")
    expect(screen.getByLabelText("Account email")).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(
      screen.getByRole("button", { name: "Actions for admin@example.com" })
    )
    expect(await screen.findByRole("button", { name: "Suspend" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Remove from project" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Remove Project admin role" })).toBeInTheDocument()
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
    await user.click(await screen.findByRole("button", { name: "Actions for admin@example.com" }))
    await user.click(await screen.findByRole("button", { name: "Suspend" }))
    const dialog = await screen.findByRole("dialog")
    await user.click(within(dialog).getByRole("button", { name: "Suspend" }))
    const alert = await within(dialog).findByRole("alert")
    expect(alert).toHaveTextContent(
      "A project must keep at least one active administrator. Make another active member a project admin first."
    )
  })

  it("explains an archived-project refusal instead of showing the raw conflict", async () => {
    installFetchStub((req) => {
      if (req.url === "/api/v1/system/access") return ok({ rollout_state: "preview", permissions: [] })
      if (req.url === "/api/v1/projects?include_archived=true") return ok([])
      if (req.url === "/api/v1/projects/p1/access") return ok(access(["members.read", "members.manage"]))
      if (req.url === "/api/v1/projects/p1/members" && req.method === "GET") return ok([MEMBER])
      if (req.method === "PATCH") return err(409, { detail: { code: "PROJECT_ARCHIVED", message: "x" } })
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
    await user.click(await screen.findByRole("button", { name: "Actions for admin@example.com" }))
    await user.click(await screen.findByRole("button", { name: "Suspend" }))
    const dialog = await screen.findByRole("dialog")
    await user.click(within(dialog).getByRole("button", { name: "Suspend" }))
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "An archived project cannot change its members."
    )
  })

  it("maps a bare 400 to the unknown-email copy on add, and not on suspend", async () => {
    installFetchStub((req) => {
      if (req.url === "/api/v1/system/access") return ok({ rollout_state: "preview", permissions: [] })
      if (req.url === "/api/v1/projects?include_archived=true") return ok([])
      if (req.url === "/api/v1/projects/p1/access") return ok(access(["members.read", "members.manage"]))
      if (req.url === "/api/v1/projects/p1/members" && req.method === "GET") return ok([MEMBER])
      if (req.method === "POST" || req.method === "PATCH") return err(400, null)
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
    await user.type(await screen.findByLabelText("Account email"), "ghost@example.com")
    await user.click(screen.getByRole("button", { name: "Add member" }))
    await waitFor(() =>
      expect(document.getElementById("member-add-email-error")).toHaveTextContent("No active account uses that email address.")
    )
    expect(screen.getByLabelText("Account email")).toHaveAttribute("aria-invalid", "true")

    await user.click(screen.getByRole("button", { name: "Actions for admin@example.com" }))
    await user.click(await screen.findByRole("button", { name: "Suspend" }))
    const dialog = await screen.findByRole("dialog")
    await user.click(within(dialog).getByRole("button", { name: "Suspend" }))
    await waitFor(() =>
      expect(within(dialog).getByRole("alert")).toHaveTextContent(
        "The change could not be saved."
      )
    )
    expect(within(dialog).getByRole("alert")).not.toHaveTextContent("email")
  })

  it("returns focus to the row menu button on Cancel and on Escape", async () => {
    const user = userEvent.setup()
    renderPage(["members.read", "members.manage"])
    await screen.findByText("admin@example.com")
    const menu = await screen.findByRole("button", { name: "Actions for admin@example.com" })
    await user.click(menu)
    await user.click(await screen.findByRole("button", { name: "Suspend" }))
    const dialog = await screen.findByRole("dialog")
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    expect(menu).toHaveFocus()

    await user.click(menu)
    await user.click(await screen.findByRole("button", { name: "Suspend" }))
    await screen.findByRole("dialog")
    await user.keyboard("{Escape}")
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    expect(menu).toHaveFocus()
  })

  it("associates the email error with the field and focuses it after a failure", async () => {
    installFetchStub((req) => {
      if (req.url === "/api/v1/system/access") return ok({ rollout_state: "preview", permissions: [] })
      if (req.url === "/api/v1/projects?include_archived=true") return ok([])
      if (req.url === "/api/v1/projects/p1/access") return ok(access(["members.read", "members.manage"]))
      if (req.url === "/api/v1/projects/p1/members" && req.method === "GET") return ok([MEMBER])
      if (req.method === "POST") return err(400, null)
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
    const email = await screen.findByLabelText("Account email")
    await user.type(email, "ghost@example.com")
    await user.click(screen.getByRole("button", { name: "Add member" }))
    const error = await screen.findByText("No active account uses that email address.")
    expect(email).toHaveAttribute("aria-invalid", "true")
    expect(email.getAttribute("aria-describedby")).toBe(error.id)
    await waitFor(() => expect(email).toHaveFocus())
  })

  it("clears the field and focuses it after a successful add", async () => {
    const stub = installFetchStub((req) => {
      if (req.url === "/api/v1/system/access") return ok({ rollout_state: "preview", permissions: [] })
      if (req.url === "/api/v1/projects?include_archived=true") return ok([])
      if (req.url === "/api/v1/projects/p1/access") return ok(access(["members.read", "members.manage"]))
      if (req.url === "/api/v1/projects/p1/members" && req.method === "GET") return ok([MEMBER])
      if (req.method === "POST") return ok({ ...MEMBER, user_id: "u2", email: "new@example.com", roles: ["project_member"] })
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
    const email = await screen.findByLabelText("Account email")
    await user.type(email, "new@example.com")
    await user.click(screen.getByRole("button", { name: "Add member" }))
    await waitFor(() => expect(stub.requests.some((req) => req.method === "POST")).toBe(true))
    await waitFor(() => expect(email).toHaveValue(""))
    await waitFor(() => expect(email).toHaveFocus())
    expect(document.activeElement?.tagName).not.toBe("BODY")
  })

  it("keeps the add draft under the project-scoped key", async () => {
    const keyA = projectStorageKey("member-draft", { accountId: "acc", projectId: "p1", schemaVersion: 1 })
    window.localStorage.setItem(keyA, JSON.stringify({ schemaVersion: 1, value: { email: "draft@a.io", role: "project_member" } }))
    renderPage(["members.read", "members.manage"])
    expect(await screen.findByLabelText("Account email")).toHaveValue("draft@a.io")
  })
})
