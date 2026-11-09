import { createContext } from "react"
import type { AuthCredentials, AuthState } from "../model/types"

/**
 * Auth surface of the browser client.
 *
 * The value holds the session status, the safe account projection, and a safe
 * error message. It holds neither the access credential nor the refresh
 * credential.
 */
export interface AuthContextValue extends AuthState {
  login: (credentials: AuthCredentials) => Promise<void>
  logout: () => Promise<void>
  restore: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined)
