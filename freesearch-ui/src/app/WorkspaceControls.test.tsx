import { describe, expect, it, vi } from "vitest"
import type { ReactNode } from "react"
import { render, screen } from "@testing-library/react"
import { ProjectsContext } from "@/domains/projects/state/context"
import type { ProjectsContextValue } from "@/domains/projects"
import {
  SETTINGS_READER_PERMISSIONS,
  SYSTEM_ADMIN_PERMISSIONS,
  projectsContextFixture,
  systemAccessFixture,
} from "@/test/accessFixtures"
import { WorkspaceControls } from "./WorkspaceControls"

vi.mock("@/context/FreeSearchContext", () => ({
  FreeSearchProvider: ({
    accountId,
    canReadControls,
    canEditControls,
    children,
  }: {
    accountId: string
    canReadControls: boolean
    canEditControls: boolean
    children: ReactNode
  }) => (
    <div data-testid="controls" data-account={accountId} data-read={String(canReadControls)} data-edit={String(canEditControls)}>
      {children}
    </div>
  ),
}))

function renderControls(overrides: Partial<ProjectsContextValue>) {
  render(
    <ProjectsContext.Provider value={projectsContextFixture(overrides)}>
      <WorkspaceControls accountId="acc">
        <p>Workspace</p>
      </WorkspaceControls>
    </ProjectsContext.Provider>
  )
  return screen.getByTestId("controls")
}

describe("WorkspaceControls", () => {
  it("derives read and edit from the system administrator's permissions", () => {
    const controls = renderControls({ systemAccess: systemAccessFixture(SYSTEM_ADMIN_PERMISSIONS) })
    expect(controls).toHaveAttribute("data-account", "acc")
    expect(controls).toHaveAttribute("data-read", "true")
    expect(controls).toHaveAttribute("data-edit", "true")
    expect(screen.getByText("Workspace")).toBeInTheDocument()
  })

  it("derives read-only control access from system.settings.read", () => {
    const controls = renderControls({ systemAccess: systemAccessFixture(SETTINGS_READER_PERMISSIONS) })
    expect(controls).toHaveAttribute("data-read", "true")
    expect(controls).toHaveAttribute("data-edit", "false")
  })

  it("keeps both flags off while the system access loads", () => {
    const controls = renderControls({ availability: "loading", systemAccess: null })
    expect(controls).toHaveAttribute("data-read", "false")
    expect(controls).toHaveAttribute("data-edit", "false")
  })
})
