import type { ReactNode } from "react"
import { render } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { ProjectScopeProvider, ProjectsProvider } from "@/domains/projects"
import type { Project } from "@/domains/projects"
import { installFetchStub } from "./fetchMock"
import type { FetchHandler, FetchStub } from "./fetchMock"
import {
  PROJECT_ADMIN_PERMISSIONS,
  PROJECT_ALPHA_ID,
  SYSTEM_ADMIN_PERMISSIONS,
  answerWorkspaceAccess,
  projectFixture,
} from "./accessFixtures"

export const HARNESS_ACCOUNT = "acc"

/** Fake provider secret used by the secret-handling tests; not a real key. */
export const FAKE_PROVIDER_KEY = "fake-provider-key-123"

export interface WorkspaceStubOptions {
  projectPermissions?: readonly string[]
  systemPermissions?: readonly string[]
  projects?: readonly Project[]
}

/** Stub the workspace access routes, then hand every other request to `handler`. */
export function installWorkspaceStub(handler: FetchHandler, options: WorkspaceStubOptions = {}): FetchStub {
  const projects = options.projects ?? [projectFixture()]
  const projectPermissions = Object.fromEntries(
    projects.map((project) => [project.id, options.projectPermissions ?? PROJECT_ADMIN_PERMISSIONS])
  )
  return installFetchStub((req) => {
    const access = answerWorkspaceAccess(req, {
      systemPermissions: options.systemPermissions ?? SYSTEM_ADMIN_PERMISSIONS,
      projects,
      projectPermissions,
    })
    return access ?? handler(req)
  })
}

/** Render one page inside the projects surface and one project scope. */
export function renderInProject(ui: ReactNode, projectId: string = PROJECT_ALPHA_ID) {
  return render(
    <MemoryRouter>
      <ProjectsProvider accountId={HARNESS_ACCOUNT}>
        <ProjectScopeProvider accountId={HARNESS_ACCOUNT} projectId={projectId}>
          {ui}
        </ProjectScopeProvider>
      </ProjectsProvider>
    </MemoryRouter>
  )
}

/** Return whether a value appears anywhere the browser could keep it. */
export function leakedAnywhere(value: string): string[] {
  const places: string[] = []
  if (document.body.innerHTML.includes(value)) places.push("DOM")
  const inputs = Array.from(document.querySelectorAll("input"))
  if (inputs.some((input) => input.value.includes(value))) places.push("input")
  if (JSON.stringify({ ...window.localStorage }).includes(value)) places.push("localStorage")
  if (JSON.stringify({ ...window.sessionStorage }).includes(value)) places.push("sessionStorage")
  if (window.location.href.includes(value)) places.push("URL")
  return places
}
