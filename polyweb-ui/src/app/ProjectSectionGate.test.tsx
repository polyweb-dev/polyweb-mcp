import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router"
import { ProjectScopeContext } from "@/domains/projects/state/context"
import type { ProjectScopeContextValue } from "@/domains/projects"
import {
  PROJECT_ALPHA_ID,
  PROJECT_MEMBER_PERMISSIONS,
  projectAccessFixture,
  projectFixture,
} from "@/test/accessFixtures"
import type { ProjectSectionId } from "./routes"
import { ProjectSectionGate } from "./ProjectSectionGate"

function scope(permissions: readonly string[]): ProjectScopeContextValue {
  return {
    projectId: PROJECT_ALPHA_ID,
    project: projectFixture(),
    accessState: { status: "ready", data: projectAccessFixture(PROJECT_ALPHA_ID, permissions) },
    refreshAccess: () => {},
  }
}

function renderGate(section: ProjectSectionId, path: string, permissions: readonly string[]) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ProjectScopeContext.Provider value={scope(permissions)}>
        <Routes>
          <Route path={`/p/${PROJECT_ALPHA_ID}`} element={<p>Overview redirect target</p>} />
          <Route
            path={path}
            element={
              <ProjectSectionGate section={section}>
                <p>Section page</p>
              </ProjectSectionGate>
            }
          />
        </Routes>
      </ProjectScopeContext.Provider>
    </MemoryRouter>
  )
}

describe("ProjectSectionGate", () => {
  it("renders a section whose permission is present", () => {
    renderGate("members", `/p/${PROJECT_ALPHA_ID}/members`, PROJECT_MEMBER_PERMISSIONS)
    expect(screen.getByText("Section page")).toBeInTheDocument()
  })

  it("redirects a section whose permission is absent to the overview", () => {
    renderGate("apiKeys", `/p/${PROJECT_ALPHA_ID}/api-keys`, PROJECT_MEMBER_PERMISSIONS)
    expect(screen.getByText("Overview redirect target")).toBeInTheDocument()
    expect(screen.queryByText("Section page")).toBeNull()
  })

  it("shows the unavailable view for an overview without project.read", () => {
    renderGate("overview", `/p/${PROJECT_ALPHA_ID}/x`, ["tokens.manage"])
    expect(screen.getByText("Project unavailable")).toBeInTheDocument()
  })
})
