import { MemoryRouter } from "react-router"
import { render } from "@testing-library/react"
import type { RenderOptions, RenderResult } from "@testing-library/react"
import { vi } from "vitest"
import type { ReactElement } from "react"
import { AuthContext } from "@/domains/auth/state/context"
import type { AuthContextValue } from "@/domains/auth/state/context"
import type { AuthStatus, UserAccount } from "@/domains/auth/model/types"
import { ProjectsContext } from "@/domains/projects/state/context"
import type { ProjectsContextValue } from "@/domains/projects"
import { projectsContextFixture, systemAccessFixture } from "./accessFixtures"
import { adminAccountFixture } from "./authFixtures"

export interface AuthenticatedRenderOptions extends Omit<RenderOptions, "wrapper"> {
  account?: UserAccount | null
  status?: AuthStatus
  route?: string
  /**
   * Effective system permissions of a ready projects context. When set (or
   * when `projects` is set), the screen renders inside a `ProjectsContext`
   * provider, the way the workspace shell provides it.
   */
  systemPermissions?: readonly string[]
  projects?: Partial<ProjectsContextValue>
}

/** Wrap one screen in a ready projects context when the options ask for one. */
function withProjects(
  ui: ReactElement,
  systemPermissions: readonly string[] | undefined,
  projects: Partial<ProjectsContextValue> | undefined
): ReactElement {
  if (systemPermissions === undefined && projects === undefined) return ui
  const value = projectsContextFixture({
    ...(systemPermissions === undefined ? {} : { systemAccess: systemAccessFixture(systemPermissions) }),
    ...projects,
  })
  return <ProjectsContext.Provider value={value}>{ui}</ProjectsContext.Provider>
}

/** Build one confirmed auth context value for tests. */
export function authenticatedContextValue(
  account: UserAccount | null,
  overrides?: Partial<AuthContextValue>
): AuthContextValue {
  return {
    status: account === null ? "anonymous" : "authenticated",
    account,
    error: null,
    login: vi.fn(async () => {}),
    logout: vi.fn(async () => {}),
    restore: vi.fn(async () => {}),
    ...overrides,
  }
}

export interface AuthenticatedRenderResult extends RenderResult {
  login: ReturnType<typeof vi.fn>
  logout: ReturnType<typeof vi.fn>
  restore: ReturnType<typeof vi.fn>
}

/**
 * Render one screen inside a confirmed auth context and a MemoryRouter.
 *
 * The context carries the safe account projection only, never a credential.
 * Tests that need the real restore flow mount AuthProvider instead.
 */
export function renderAuthenticated(
  ui: ReactElement,
  options?: AuthenticatedRenderOptions
): AuthenticatedRenderResult {
  const {
    account = adminAccountFixture(),
    status,
    route = "/",
    systemPermissions,
    projects,
    ...renderOptions
  } = options ?? {}
  const login = vi.fn(async () => {})
  const logout = vi.fn(async () => {})
  const restore = vi.fn(async () => {})
  const value: AuthContextValue = {
    status: status ?? (account === null ? "anonymous" : "authenticated"),
    account,
    error: null,
    login,
    logout,
    restore,
  }
  const result = render(
    <MemoryRouter initialEntries={[route]}>
      <AuthContext.Provider value={value}>
        {withProjects(ui, systemPermissions, projects)}
      </AuthContext.Provider>
    </MemoryRouter>,
    renderOptions
  )
  return { ...result, login, logout, restore }
}
