/**
 * Auth contracts of the browser client.
 *
 * The refresh credential never appears in a type of this module: it lives in a
 * strict HttpOnly cookie. The access credential lives in the memory store of
 * `shared/api/session.ts`, not in React state and not in persisted storage.
 */

/** Account class that authorizes each control-plane surface. */
export type UserRole = "admin" | "developer" | "agent"

/** The three roles, in display order, for a role control. */
export const USER_ROLES: readonly UserRole[] = ["admin", "developer", "agent"]

/** Display label of each role, in a role control and in a creation receipt. */
export const ROLE_LABELS: Record<UserRole, string> = {
  admin: "Admin",
  developer: "Developer",
  agent: "Agent",
}

/** Safe account projection. It holds no password hash and no session family. */
export interface UserAccount {
  id: string
  email: string
  role: UserRole
  is_active: boolean
  is_superuser: boolean
  is_verified: boolean
}

/** Browser login and refresh projection. It holds no refresh credential. */
export interface BrowserAccessResponse {
  access_token: string
  token_type: "bearer"
  expires_in: number
  refresh_expires_in: number
}

/** Submitted credentials of a login. */
export interface AuthCredentials {
  email: string
  password: string
}

/** Submitted credentials of an account creation, with the selected role. */
export interface RegistrationCredentials extends AuthCredentials {
  role: UserRole
}

/**
 * Session status of the browser client.
 *
 * `restoring` covers the cookie restore. `unavailable` covers a network or
 * server failure, which is never the same as a successful anonymous session.
 */
export type AuthStatus = "restoring" | "anonymous" | "authenticated" | "unavailable"

export interface AuthState {
  status: AuthStatus
  account: UserAccount | null
  error: string | null
}

/** Return whether an unknown value is one of the three roles. */
export function isUserRole(value: unknown): value is UserRole {
  return value === "admin" || value === "developer" || value === "agent"
}
