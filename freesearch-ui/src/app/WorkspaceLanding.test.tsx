import { afterEach, describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { MemoryRouter, Route, Routes, useLocation } from "react-router"
import { ProjectsContext } from "@/domains/projects/state/context"
import { lastProjectKey } from "@/domains/projects"
import type { ProjectsContextValue } from "@/domains/projects"
import {
  PROJECT_ALPHA_ID,
  PROJECT_BETA_ID,
  projectFixture,
  projectsContextFixture,
} from "@/test/accessFixtures"
import { WorkspaceLanding } from "./WorkspaceLanding"

const ACCOUNT = "acc"

function PathProbe() {
  return <p data-testid="path">{useLocation().pathname}</p>
}

function renderLanding(route: string, overrides: Partial<ProjectsContextValue>) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <ProjectsContext.Provider value={projectsContextFixture({ accountId: ACCOUNT, ...overrides })}>
        <Routes>
          <Route path="/projects" element={<PathProbe />} />
          <Route path="/p/:projectId" element={<PathProbe />} />
          <Route path="*" element={<WorkspaceLanding />} />
        </Routes>
      </ProjectsContext.Provider>
    </MemoryRouter>
  )
}

describe("WorkspaceLanding", () => {
  afterEach(() => window.localStorage.clear())

  it("lands on the remembered project when it is still readable", () => {
    window.localStorage.setItem(lastProjectKey(ACCOUNT), PROJECT_BETA_ID)
    renderLanding("/", {
      projects: [projectFixture(), projectFixture({ id: PROJECT_BETA_ID, name: "Beta" })],
    })
    expect(screen.getByTestId("path").textContent).toBe(`/p/${PROJECT_BETA_ID}`)
  })

  it("falls back to the project list for a stale remembered project", () => {
    window.localStorage.setItem(lastProjectKey(ACCOUNT), "gone")
    renderLanding("/unknown/path", { projects: [projectFixture({ id: PROJECT_ALPHA_ID })] })
    expect(screen.getByTestId("path").textContent).toBe("/projects")
  })

  it("falls back to the project list without a remembered project and never writes one", () => {
    renderLanding("/", { projects: [projectFixture()] })
    expect(screen.getByTestId("path").textContent).toBe("/projects")
    expect(window.localStorage.getItem(lastProjectKey(ACCOUNT))).toBeNull()
  })

  it("waits for the project list instead of redirecting", () => {
    renderLanding("/", { availability: "loading", systemAccess: null })
    expect(screen.getByRole("status")).toHaveTextContent("Loading workspace…")
    expect(screen.queryByTestId("path")).toBeNull()
  })
})
