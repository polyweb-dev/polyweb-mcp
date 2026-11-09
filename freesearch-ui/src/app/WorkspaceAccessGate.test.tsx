import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { ProjectsContext } from "@/domains/projects/state/context"
import { projectsContextFixture } from "@/test/accessFixtures"
import type { ProjectsContextValue } from "@/domains/projects"
import { WorkspaceAccessGate } from "./WorkspaceAccessGate"

function renderGate(overrides: Partial<ProjectsContextValue>) {
  return render(
    <ProjectsContext.Provider value={projectsContextFixture(overrides)}>
      <WorkspaceAccessGate>
        <p>Gated page</p>
      </WorkspaceAccessGate>
    </ProjectsContext.Provider>
  )
}

describe("WorkspaceAccessGate", () => {
  it("shows the loading status instead of the page while access loads", () => {
    renderGate({ availability: "loading", systemAccess: null })
    expect(screen.getByRole("status")).toHaveTextContent("Loading workspace…")
    expect(screen.queryByText("Gated page")).toBeNull()
  })

  it("shows the failure alert with a Retry that reloads the access", async () => {
    const reloadProjects = vi.fn(() => Promise.resolve(null))
    renderGate({ availability: "unavailable", systemAccess: null, reloadProjects })
    expect(screen.getByRole("alert")).toHaveTextContent("The workspace could not be loaded.")
    expect(screen.queryByText("Gated page")).toBeNull()
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }))
    expect(reloadProjects).toHaveBeenCalledTimes(1)
  })

  it("renders the page once access is available", () => {
    renderGate({ availability: "available" })
    expect(screen.getByText("Gated page")).toBeInTheDocument()
    expect(screen.queryByRole("status")).toBeNull()
  })
})
