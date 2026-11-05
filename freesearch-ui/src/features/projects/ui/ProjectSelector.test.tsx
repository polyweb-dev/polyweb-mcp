import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes, useLocation } from "react-router"
import { err, installFetchStub, ok } from "@/test/fetchMock"
import { ProjectsProvider, lastProjectKey } from "@/domains/projects"
import { parseProjectPath, projectIdFromPath, projectPath } from "@/app/routes"
import { ProjectSelector } from "./ProjectSelector"

const P_A = { id: "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa", account_id: "acc", name: "Alpha", slug: "alpha", status: "active", created_by: "u", created_at: "t", version: 1 }
const P_B = { id: "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb", account_id: "acc", name: "Beta", slug: "beta", status: "archived", created_by: "u", created_at: "t", version: 1 }

/** Mirror of the shell wiring: the URL project and a section-keeping path builder. */
function SelectorAtRoute() {
  const { pathname } = useLocation()
  const section = parseProjectPath(pathname)?.section ?? "overview"
  return (
    <ProjectSelector
      collapsed={false}
      currentProjectId={projectIdFromPath(pathname)}
      pathForProject={(id) => projectPath(id, section)}
    />
  )
}

function PathProbe() {
  const { pathname } = useLocation()
  return <div data-testid="path">{pathname}</div>
}

function renderSelector(route: string, systemOk = true) {
  installFetchStub((req) => {
    if (req.url === "/api/v1/system/access") {
      return systemOk ? ok({ rollout_state: "preview", permissions: [] }) : err(404, null)
    }
    if (req.url === "/api/v1/projects?include_archived=true") return ok([P_A, P_B])
    return err(404, null)
  })
  return render(
    <MemoryRouter initialEntries={[route]}>
      <ProjectsProvider accountId="acc">
        <Routes>
          <Route path="*" element={<><SelectorAtRoute /><PathProbe /></>} />
        </Routes>
      </ProjectsProvider>
    </MemoryRouter>
  )
}

describe("ProjectSelector", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.localStorage.clear()
  })

  it("renders nothing while the projects surface is unavailable", async () => {
    renderSelector("/playground", false)
    await waitFor(() => expect(screen.queryByRole("navigation", { name: "Projects" })).toBeNull())
  })

  it("lists projects with a Preview badge and keeps the members section", async () => {
    const user = userEvent.setup()
    renderSelector(`/p/${P_A.id}/members`)
    const nav = await screen.findByRole("navigation", { name: "Projects" })
    expect(nav).toBeInTheDocument()
    expect(screen.getByText("Alpha")).toBeInTheDocument()
    expect(screen.getByText("Project · Preview")).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: /Select project/ }))
    await user.click(screen.getByRole("menuitem", { name: /Beta/ }))
    await waitFor(() =>
      expect(screen.getByTestId("path").textContent).toBe(`/p/${P_B.id}/members`)
    )
  })

  it("keeps the API keys section on a switch and remembers only the explicit choice", async () => {
    const user = userEvent.setup()
    renderSelector(`/p/${P_A.id}/api-keys`)
    await screen.findByRole("navigation", { name: "Projects" })
    expect(window.localStorage.getItem(lastProjectKey("acc"))).toBeNull()

    await user.click(screen.getByRole("button", { name: /Select project/ }))
    await user.click(screen.getByRole("menuitem", { name: /Beta/ }))
    await waitFor(() =>
      expect(screen.getByTestId("path").textContent).toBe(`/p/${P_B.id}/api-keys`)
    )
    expect(window.localStorage.getItem(lastProjectKey("acc"))).toBe(P_B.id)
  })

  it("names the trigger with the current project for assistive tech", async () => {
    renderSelector(`/p/${P_A.id}`)
    const trigger = await screen.findByRole("button", {
      name: "Select project (current: Alpha)",
    })
    expect(trigger).toBeInTheDocument()
  })

  it("closes the menu on Escape and returns focus to the trigger", async () => {
    const user = userEvent.setup()
    renderSelector("/playground")
    const trigger = await screen.findByRole("button", { name: /Select project/ })
    await user.click(trigger)
    const menu = await screen.findByRole("menu", { name: "Projects" })
    await waitFor(() => expect(menu.contains(document.activeElement)).toBe(true))
    await user.keyboard("{Escape}")
    await waitFor(() =>
      expect(screen.queryByRole("menu", { name: "Projects" })).toBeNull()
    )
    expect(document.activeElement).toBe(trigger)
  })

  it("closes the menu on an outside click", async () => {
    const user = userEvent.setup()
    renderSelector("/playground")
    await user.click(await screen.findByRole("button", { name: /Select project/ }))
    await screen.findByRole("menu", { name: "Projects" })
    await user.click(document.body)
    await waitFor(() =>
      expect(screen.queryByRole("menu", { name: "Projects" })).toBeNull()
    )
  })

  it("navigates to the project root from a non-project route and to the list", async () => {
    const user = userEvent.setup()
    renderSelector("/playground")
    await screen.findByRole("navigation", { name: "Projects" })
    await user.click(screen.getByRole("button", { name: /Select project/ }))
    await user.click(screen.getByRole("menuitem", { name: /Alpha/ }))
    await waitFor(() =>
      expect(screen.getByTestId("path").textContent).toBe(`/p/${P_A.id}`)
    )
    await user.click(screen.getByRole("button", { name: /Select project/ }))
    await user.click(screen.getByRole("menuitem", { name: "All projects" }))
    await waitFor(() => expect(screen.getByTestId("path").textContent).toBe("/projects"))
  })
})
