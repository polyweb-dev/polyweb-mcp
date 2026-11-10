/**
 * Auth contracts of the browser client.
 *
 * The refresh credential never appears in a type of this module: it lives in a
 * strict HttpOnly cookie. The access credential lives in the memory store of
 * `shared/api/session.ts`, not in React state and not in persisted storage.
 */

/** Identity provider that owns an account. */
export type AuthProviderKind = "local" | "workos"

/**
 * Safe account projection of `GET /users/me`, registration and provisioning.
 *
 * It holds no password hash, no session family, and no role or privilege
 * flag: authority comes from the live system and project access descriptors.
 */
export interface UserAccount {
  id: string
  email: string
  auth_provider: AuthProviderKind
  auth_provider_id: string | null
  username: string | null
  first_name: string | null
  last_name: string | null
  is_active: boolean
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

/**
 * Submitted credentials of an account creation.
 *
 * The public signup always sends the username, the first name, and the
 * last name alongside the email and the password.
 */
export interface RegistrationCredentials extends AuthCredentials {
  username: string
  first_name: string
  last_name: string
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

/**
 * Return the display name of one account, or `null` when it has none.
 *
 * The full name wins over the username; the email stays the identity line.
 * Identity resolution is intentionally local: it stays identical for every
 * named identity view without coupling domains.
 */
import { displayNameFromProfile } from "@/shared/lib/identity"

export function accountDisplayName(account: {
  username: string | null
  first_name: string | null
  last_name: string | null
}): string | null {
  return displayNameFromProfile(account)
}
