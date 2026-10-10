import { MemoryRouter } from "react-router"
import { render } from "@testing-library/react"
import type { RenderOptions, RenderResult } from "@testing-library/react"
import { vi } from "vitest"
import type { ReactElement } from "react"
import { AuthContext } from "@/domains/auth/state/context"
import type { AuthContextValue } from "@/domains/auth/state/context"
import type { AuthStatus, UserAccount } from "@/domains/auth/model/types"
import { adminAccountFixture } from "./authFixtures"

export interface AuthenticatedRenderOptions extends Omit<RenderOptions, "wrapper"> {
  account?: UserAccount | null
  status?: AuthStatus
  route?: string
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
  const { account = adminAccountFixture(), status, route = "/", ...renderOptions } = options ?? {}
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
      <AuthContext.Provider value={value}>{ui}</AuthContext.Provider>
    </MemoryRouter>,
    renderOptions
  )
  return { ...result, login, logout, restore }
}
