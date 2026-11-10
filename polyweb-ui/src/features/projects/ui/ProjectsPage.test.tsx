import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, useLocation } from "react-router"
import { err, installFetchStub, ok } from "@/test/fetchMock"
import { ProjectsProvider } from "@/domains/projects"
import { ProjectsPage } from "./ProjectsPage"

const PROJECT = { id: "p-1", account_id: "a", name: "Alpha", slug: "alpha", status: "active", created_by: "u", created_at: "t", version: 1 }
const NEW_PROJECT = { ...PROJECT, id: "p-new", name: "New" }

function LocationProbe() {
  const { pathname } = useLocation()
  return <div data-testid="location">{pathname}</div>
}

function renderPage(permissions: string[], projects: unknown[] = []) {
  const state = [...projects]
  const stub = installFetchStub((req) => {
    if (req.url === "/api/v1/system/access") return ok({ rollout_state: "preview", permissions })
    if (req.url === "/api/v1/projects?include_archived=true" && req.method === "GET") return ok(state)
    if (req.method === "POST" && req.url === "/api/v1/projects") {
      const body = (req.body ?? {}) as { name?: unknown }
      state.push({
        ...NEW_PROJECT,
        name: typeof body.name === "string" ? body.name : NEW_PROJECT.name,
      })
      return ok(state[state.length - 1], 201)
    }
    return err(404, null)
  })
  return {
    ...render(
      <MemoryRouter>
        <ProjectsProvider accountId="acc">
          <ProjectsPage />
          <LocationProbe />
        </ProjectsProvider>
      </MemoryRouter>
    ),
    stub,
  }
}

describe("ProjectsPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.localStorage.clear()
  })

  it("offers a continue link for a stored valid project", async () => {
    window.localStorage.setItem(
      "polyweb:last-project:v1:acc",
      "p-1"
    )
    renderPage([], [PROJECT])
    const table = await screen.findByRole("table", { name: "Projects" })
    const row = within(table).getByRole("row", { name: /Alpha/ })
    expect(within(row).getByRole("link", { name: "Alpha" })).toHaveAttribute("href", "/p/p-1")
    expect(within(row).getByText("Last opened")).toBeInTheDocument()
    expect(within(row).getByText("alpha")).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: /Continue with/ })).toBeNull()
  })

  it("sorts projects by name, drops the status column and tags only an archived project", async () => {
    const archived = { ...PROJECT, id: "p-0", name: "Zulu", slug: "zulu", status: "archived" }
    const beta = { ...PROJECT, id: "p-2", name: "Beta", slug: "beta" }
    renderPage([], [archived, beta, PROJECT])
    const table = await screen.findByRole("table", { name: "Projects" })
    const headers = within(table).getAllByRole("columnheader").map((cell) => cell.textContent)
    expect(headers.slice(0, 3)).toEqual(["Name", "Slug", "Created"])
    const links = within(table).getAllByRole("link").map((link) => link.textContent)
    expect(links).toEqual(["Alpha", "Beta", "Zulu"])
    expect(within(table).getAllByText("Archived")).toHaveLength(1)
    expect(within(table).queryByText("Active")).toBeNull()
  })

  it("hides the continue link for a stored id absent from the list", async () => {
    window.localStorage.setItem("polyweb:last-project:v1:acc", "p-gone")
    renderPage([], [PROJECT])
    await screen.findByRole("link", { name: "Alpha" })
    expect(screen.queryByText("Last opened")).toBeNull()
    expect(screen.queryByRole("link", { name: /Continue with/ })).toBeNull()
  })

  it("shows the zero-membership guidance when the list is empty", async () => {
    renderPage([])
    await screen.findByText("You are not a member of any project")
    expect(screen.getByText("Ask a system administrator to add you")).toBeInTheDocument()
    expect(screen.queryByRole("form", { name: "Create project" })).toBeNull()
  })

  it("shows the create form only with the project.create permission", async () => {
    renderPage(["project.create"])
    await screen.findByText("No projects yet")
    expect(screen.getByText("Create your first project to get started.")).toBeInTheDocument()
    expect(screen.getByLabelText("First administrator email (optional)")).toHaveValue("")
    expect(
      screen.getByText("Leave blank to make yourself the administrator.")
    ).toBeInTheDocument()
  })

  it("shows an error with Retry instead of hiding the page when the load fails", async () => {
    let fail = true
    installFetchStub((req) => {
      if (req.url === "/api/v1/system/access") {
        return fail ? err(503, null) : ok({ rollout_state: "preview", permissions: [] })
      }
      if (req.url === "/api/v1/projects?include_archived=true") return ok([PROJECT])
      return err(404, null)
    })
    render(
      <MemoryRouter>
        <ProjectsProvider accountId="acc">
          <ProjectsPage />
        </ProjectsProvider>
      </MemoryRouter>
    )
    expect(await screen.findByRole("alert")).toHaveTextContent("The project list could not be loaded.")
    fail = false
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }))
    expect(await screen.findByRole("link", { name: "Alpha" })).toBeInTheDocument()
  })

  it("loads the list on entry and on manual retry", async () => {
    let fail = true
    const stub = installFetchStub((req) => {
      if (req.url === "/api/v1/system/access") {
        return fail ? err(503, null) : ok({ rollout_state: "preview", permissions: [] })
      }
      if (req.url === "/api/v1/projects?include_archived=true") return ok([PROJECT])
      return err(404, null)
    })
    render(
      <MemoryRouter>
        <ProjectsProvider accountId="acc">
          <ProjectsPage />
        </ProjectsProvider>
      </MemoryRouter>
    )
    expect(await screen.findByRole("alert")).toHaveTextContent("The project list could not be loaded.")
    const firstLoad = stub.requestsTo(/\/api\/v1\/projects\?include_archived=true/).length
    expect(firstLoad).toBeGreaterThanOrEqual(1)
    fail = false
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }))
    await screen.findByRole("link", { name: "Alpha" })
    expect(stub.requestsTo(/\/api\/v1\/projects\?include_archived=true/).length).toBeGreaterThan(firstLoad)
  })

  it("hides the create form with system.projects.create alone", async () => {
    renderPage(["system.projects.create"])
    await screen.findByText("You are not a member of any project")
    expect(screen.queryByRole("form", { name: "Create project" })).toBeNull()
  })

  it("hides the create form without a creation permission", async () => {
    renderPage(["system.settings.write"])
    await screen.findByText("You are not a member of any project")
    expect(screen.queryByRole("form", { name: "Create project" })).toBeNull()
  })

  it("sends no admin identifier on a name-only submit and navigates to the created project", async () => {
    const { stub } = renderPage(["project.create"], [])
    const user = userEvent.setup()
    const nameField = await screen.findByLabelText("Project name")
    await user.type(nameField, "New")
    expect(screen.getByLabelText("First administrator email (optional)")).toHaveValue("")
    await user.click(screen.getByRole("button", { name: "Create project" }))
    expect(await screen.findByTestId("location")).toHaveTextContent("/p/p-new")
    const table = await screen.findByRole("table", { name: "Projects" })
    expect(within(table).getByRole("link", { name: "New" })).toHaveAttribute("href", "/p/p-new")
    const posts = stub.requests.filter((r) => r.method === "POST")
    expect(posts).toHaveLength(1)
    expect(posts[0]?.body).toEqual({ name: "New" })
    expect(Object.keys(posts[0]?.body as object).sort()).toEqual(["name"])
  })

  it("asks for a refresh when the created project is missing from the reloaded list", async () => {
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
          <ProjectsPage />
          <LocationProbe />
        </ProjectsProvider>
      </MemoryRouter>
    )
    const nameField = await screen.findByLabelText("Project name")
    await user.type(nameField, "New")
    await user.click(screen.getByRole("button", { name: "Create project" }))
    await screen.findByText("Project created. Refresh the list to open it.")
    expect(screen.getByTestId("location")).toHaveTextContent("/")
    expect(stub.requests.filter((r) => r.method === "POST")).toHaveLength(1)
  })

  it("sends the explicit administrator email when filled", async () => {
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
          <ProjectsPage />
        </ProjectsProvider>
      </MemoryRouter>
    )
    await user.type(await screen.findByLabelText("Project name"), "New")
    await user.type(screen.getByLabelText("First administrator email (optional)"), "boss@example.com")
    await user.click(screen.getByRole("button", { name: "Create project" }))
    await screen.findByText("Project created. Refresh the list to open it.")
    const posts = stub.requests.filter((r) => r.method === "POST")
    expect(posts).toHaveLength(1)
    expect(posts[0]?.body).toEqual({ name: "New", initial_admin_email: "boss@example.com" })
  })

  it("names an unknown first-administrator email on a bare 400 from create", async () => {
    installFetchStub((req) => {
      if (req.url === "/api/v1/system/access") return ok({ rollout_state: "preview", permissions: ["project.create"] })
      if (req.url === "/api/v1/projects?include_archived=true" && req.method === "GET") return ok([])
      if (req.method === "POST" && req.url === "/api/v1/projects") return err(400, null)
      return err(404, null)
    })
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <ProjectsProvider accountId="acc">
          <ProjectsPage />
        </ProjectsProvider>
      </MemoryRouter>
    )
    await user.type(await screen.findByLabelText("Project name"), "New")
    await user.type(
      screen.getByLabelText("First administrator email (optional)"),
      "ghost@example.com"
    )
    await user.click(screen.getByRole("button", { name: "Create project" }))
    expect(await screen.findByText("No active account uses that email address.")).toBeInTheDocument()
    expect(screen.getByLabelText("First administrator email (optional)")).toHaveAttribute("aria-invalid", "true")
  })

  it("marks an empty project name on its field without a request", async () => {
    const stub = installFetchStub((req) => {
      if (req.url === "/api/v1/system/access") return ok({ rollout_state: "preview", permissions: ["project.create"] })
      if (req.url === "/api/v1/projects?include_archived=true" && req.method === "GET") return ok([])
      return err(404, null)
    })
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <ProjectsProvider accountId="acc">
          <ProjectsPage />
        </ProjectsProvider>
      </MemoryRouter>
    )
    await screen.findByLabelText("Project name")
    await user.click(screen.getByRole("button", { name: "Create project" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter a project name")
    expect(screen.getByLabelText("Project name")).toHaveAttribute("aria-invalid", "true")
    expect(stub.requests.filter((r) => r.method === "POST")).toHaveLength(0)
  })
})
