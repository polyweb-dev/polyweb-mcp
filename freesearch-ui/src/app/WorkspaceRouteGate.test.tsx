import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router"
import { ProjectsContext } from "@/domains/projects/state/context"
import {
  SETTINGS_READER_PERMISSIONS,
  projectsContextFixture,
  systemAccessFixture,
} from "@/test/accessFixtures"
import type { ProjectsContextValue } from "@/domains/projects"
import type { TabId } from "./routes"
import { WorkspaceRouteGate } from "./WorkspaceRouteGate"

function renderAt(id: TabId, path: string, overrides: Partial<ProjectsContextValue>) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ProjectsContext.Provider value={projectsContextFixture(overrides)}>
        <Routes>
          <Route path="/" element={<p>Workspace entry</p>} />
          <Route
            path={path}
            element={
              <WorkspaceRouteGate id={id}>
                <p>Gated page</p>
              </WorkspaceRouteGate>
            }
          />
        </Routes>
      </ProjectsContext.Provider>
    </MemoryRouter>
  )
}

describe("WorkspaceRouteGate", () => {
  it("renders an open route at once, even while access loads", () => {
    renderAt("playground", "/playground", { availability: "loading", systemAccess: null })
    expect(screen.getByText("Gated page")).toBeInTheDocument()
  })

  it("shows the loading status for a gated route instead of redirecting", () => {
    renderAt("settings", "/settings", { availability: "loading", systemAccess: null })
    expect(screen.getByRole("status")).toHaveTextContent("Loading workspace…")
    expect(screen.queryByText("Workspace entry")).toBeNull()
  })

  it("shows the failure alert for a gated route when access fails", () => {
    renderAt("routing", "/routing", { availability: "unavailable", systemAccess: null })
    expect(screen.getByRole("alert")).toHaveTextContent("The workspace could not be loaded.")
  })

  it("renders a gated route with its system permission", () => {
    renderAt("settings", "/settings", { systemAccess: systemAccessFixture(SETTINGS_READER_PERMISSIONS) })
    expect(screen.getByText("Gated page")).toBeInTheDocument()
  })

  it("redirects an unauthorized direct URL to the workspace entry", () => {
    renderAt("adminUsers", "/admin/users", { systemAccess: systemAccessFixture(SETTINGS_READER_PERMISSIONS) })
    expect(screen.getByText("Workspace entry")).toBeInTheDocument()
    expect(screen.queryByText("Gated page")).toBeNull()
  })
})
