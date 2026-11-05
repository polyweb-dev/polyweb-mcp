import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { ProjectScopeContext } from "@/domains/projects/state/context"
import { ProjectsContext } from "@/domains/projects/state/context"
import type { ProjectScopeContextValue, ProjectsContextValue } from "@/domains/projects"
import { writeLastProject } from "@/domains/projects"
import { err, installFetchStub, ok } from "@/test/fetchMock"
import {
  PROJECT_ADMIN_PERMISSIONS,
  PROJECT_ALPHA_ID,
  PROJECT_MEMBER_PERMISSIONS,
  projectAccessFixture,
  projectFixture,
} from "@/test/accessFixtures"
import { ProjectNav } from "./SidebarProjectNav"

function scope(accessState: ProjectScopeContextValue["accessState"]): ProjectScopeContextValue {
  return { projectId: PROJECT_ALPHA_ID, project: projectFixture(), accessState, refreshAccess: () => {} }
}

function ready(permissions: readonly string[]): ProjectScopeContextValue["accessState"] {
  return { status: "ready", data: projectAccessFixture(PROJECT_ALPHA_ID, permissions) }
}

function renderNav(value: ProjectScopeContextValue | undefined, route: string, collapsed = false) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <ProjectScopeContext.Provider value={value}>
        <ProjectNav collapsed={collapsed} />
      </ProjectScopeContext.Provider>
    </MemoryRouter>
  )
}

function links(): HTMLElement[] {
  return within(screen.getByRole("navigation", { name: "Project" })).queryAllByRole("link")
}

describe("ProjectNav", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.localStorage.clear()
  })

  it("renders nothing on a global route", () => {
    renderNav(undefined, "/projects")
    expect(screen.queryByRole("navigation", { name: "Project" })).toBeNull()
  })

  it("lists every project section in order for a project administrator", () => {
    renderNav(scope(ready(PROJECT_ADMIN_PERMISSIONS)), `/p/${PROJECT_ALPHA_ID}/members`)
    expect(links().map((link) => link.getAttribute("aria-label"))).toEqual([
      "Overview",
      "Playground",
      "Activity",
      "Usage",
      "Providers",
      "Settings",
      "Members",
      "API keys",
    ])
    expect(links().map((link) => link.getAttribute("href"))).toEqual([
      `/p/${PROJECT_ALPHA_ID}`,
      `/p/${PROJECT_ALPHA_ID}/playground`,
      `/p/${PROJECT_ALPHA_ID}/activity`,
      `/p/${PROJECT_ALPHA_ID}/usage`,
      `/p/${PROJECT_ALPHA_ID}/providers`,
      `/p/${PROJECT_ALPHA_ID}/settings`,
      `/p/${PROJECT_ALPHA_ID}/members`,
      `/p/${PROJECT_ALPHA_ID}/api-keys`,
    ])
  })

  it("marks only the active section as current", () => {
    renderNav(scope(ready(PROJECT_ADMIN_PERMISSIONS)), `/p/${PROJECT_ALPHA_ID}/members`)
    expect(screen.getByRole("link", { name: "Members" })).toHaveAttribute("aria-current", "page")
    expect(screen.getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current")
  })

  it("hides a section whose permission is absent", () => {
    renderNav(scope(ready(PROJECT_MEMBER_PERMISSIONS)), `/p/${PROJECT_ALPHA_ID}`)
    expect(links().map((link) => link.getAttribute("aria-label"))).toEqual([
      "Overview",
      "Playground",
      "Activity",
      "Usage",
      "Providers",
      "Settings",
      "Members",
    ])
  })

  it("shows the Playground with either execution permission and hides it with neither", () => {
    renderNav(scope(ready(["project.read", "fetch.execute"])), `/p/${PROJECT_ALPHA_ID}`)
    expect(links().map((link) => link.getAttribute("aria-label"))).toEqual(["Overview", "Playground"])
  })

  it("hides Playground, Activity and Usage without their permissions", () => {
    renderNav(scope(ready(["project.read", "members.read"])), `/p/${PROJECT_ALPHA_ID}`)
    expect(links().map((link) => link.getAttribute("aria-label"))).toEqual(["Overview", "Members"])
  })

  it("shows no section link while the project access loads", () => {
    renderNav(scope({ status: "loading" }), `/p/${PROJECT_ALPHA_ID}`)
    expect(links()).toHaveLength(0)
  })

  it("keeps the accessible name and title on the collapsed rail", () => {
    renderNav(scope(ready(PROJECT_ADMIN_PERMISSIONS)), `/p/${PROJECT_ALPHA_ID}`, true)
    const apiKeys = screen.getByRole("link", { name: "API keys" })
    expect(apiKeys).toHaveAttribute("title", "API keys")
    expect(apiKeys.textContent).toBe("")
  })
})

describe("ProjectNav on global routes", () => {
  const project = projectFixture({ name: "Customer Research — Shared Workspace" })

  function projectsValue(): ProjectsContextValue {
    return {
      accountId: "acc",
      availability: "available",
      rolloutState: "preview",
      systemAccess: null,
      projects: [project],
      reloadProjects: async () => [project],
    }
  }

  function renderGlobalNav(access: "ok" | "error" | "slow") {
    installFetchStub((req) => {
      if (req.url === `/api/v1/projects/${PROJECT_ALPHA_ID}/access`) {
        if (access === "error") return err(500, null)
        if (access === "slow") return new Promise(() => {})
        return ok(projectAccessFixture(PROJECT_ALPHA_ID, ["project.read", "members.read"]))
      }
      return err(404, null)
    })
    writeLastProject("acc", PROJECT_ALPHA_ID)
    return render(
      <MemoryRouter initialEntries={["/routing"]}>
        <ProjectsContext.Provider value={projectsValue()}>
          <ProjectScopeContext.Provider value={undefined}>
            <ProjectNav collapsed={false} />
          </ProjectScopeContext.Provider>
        </ProjectsContext.Provider>
      </MemoryRouter>
    )
  }

  it("shows the Back link and only the sections the access permits", async () => {
    renderGlobalNav("ok")
    const back = await screen.findByRole("link", {
      name: `Back to ${project.name}`,
    })
    expect(back).toHaveAttribute("href", `/p/${PROJECT_ALPHA_ID}`)
    await waitFor(() =>
      expect(links().map((link) => link.getAttribute("aria-label"))).toEqual([
        `Back to ${project.name}`,
        "Overview",
        "Members",
      ])
    )
    expect(screen.queryByRole("link", { name: "Providers" })).toBeNull()
  })

  it("shows only the Back link while the access loads or fails", async () => {
    renderGlobalNav("error")
    const back = await screen.findByRole("link", {
      name: `Back to ${project.name}`,
    })
    expect(back).toHaveAttribute("href", `/p/${PROJECT_ALPHA_ID}`)
    await waitFor(() => expect(links()).toHaveLength(1))
    expect(links()[0].getAttribute("aria-label")).toBe(`Back to ${project.name}`)
  })
})
