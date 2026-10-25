import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router"
import { err, installFetchStub, ok } from "@/test/fetchMock"
import { ProjectsProvider } from "@/domains/projects"
import { ProjectsPage } from "./ProjectsPage"

const PROJECT = { id: "p-1", account_id: "a", name: "Alpha", slug: "alpha", status: "active", created_by: "u", created_at: "t", version: 1 }
const NEW_PROJECT = { ...PROJECT, id: "p-new", name: "New" }

function renderPage(permissions: string[], projects: unknown[] = [], createList: unknown[] = []) {
  installFetchStub((req) => {
    if (req.url === "/api/v1/system/access") return ok({ rollout_state: "preview", permissions })
    if (req.url === "/api/v1/projects?include_archived=true") return ok(projects)
    if (req.url === "/api/v1/projects") return ok(projects)
    if (req.method === "POST" && req.url === "/api/v1/projects") return ok(NEW_PROJECT, 201)
    return err(404, null)
  })
  void createList
  return render(
    <MemoryRouter>
      <ProjectsProvider accountId="acc">
        <ProjectsPage defaultAdminEmail="me@example.com" />
      </ProjectsProvider>
    </MemoryRouter>
  )
}

describe("ProjectsPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.localStorage.clear()
  })

  it("offers a continue link for a stored valid project", async () => {
    window.localStorage.setItem(
      "freesearch:last-project:v1:acc",
      "p-1"
    )
    renderPage([], [PROJECT])
    expect(await screen.findByRole("link", { name: "Continue with Alpha" })).toHaveAttribute(
      "href",
      "/p/p-1"
    )
  })

  it("hides the continue link for a stored id absent from the list", async () => {
    window.localStorage.setItem("freesearch:last-project:v1:acc", "p-gone")
    renderPage([], [PROJECT])
    await screen.findByRole("link", { name: "Alpha" })
    expect(screen.queryByRole("link", { name: /Continue with/ })).toBeNull()
  })

  it("shows the zero-membership guidance when the list is empty", async () => {
    renderPage([])
    await screen.findByText("You are not a member of any project.")
    expect(screen.getByText("Ask a system administrator to add you.")).toBeInTheDocument()
    expect(screen.queryByRole("form", { name: "Create project" })).toBeNull()
  })

  it("shows the create form only with the project.create permission", async () => {
    renderPage(["project.create"])
    await screen.findByText("You are not a member of any project.")
    expect(screen.getByLabelText("First administrator email")).toHaveValue("me@example.com")
  })

  it("reports a created project the caller is not a member of", async () => {
    const stub = installFetchStub((req) => {
      if (req.url === "/api/v1/system/access") return ok({ rollout_state: "preview", permissions: ["project.create"] })
      if (req.url === "/api/v1/projects?include_archived=true" && req.method === "GET") return ok([])
      if (req.method === "POST" && req.url === "/api/v1/projects") return ok(NEW_PROJECT, 201)
      return err(404, null)
    })
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <ProjectsProvider accountId="acc">
          <ProjectsPage defaultAdminEmail="me@example.com" />
        </ProjectsProvider>
      </MemoryRouter>
    )
    const nameField = await screen.findByLabelText("Project name")
    await user.type(nameField, "New")
    await user.click(screen.getByRole("button", { name: "Create project" }))
    await screen.findByText("Project created. You are not a member of it.")
    expect(stub.requests.filter((r) => r.method === "POST")).toHaveLength(1)
  })
})
