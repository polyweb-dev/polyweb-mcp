import { useContext } from "react"
import { AuthContext } from "./context"
import type { AuthContextValue } from "./context"

/** Return the auth surface, or reject a component outside `AuthProvider`. */
export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext)
  if (value === undefined) throw new Error("useAuth must be used inside AuthProvider")
  return value
}
