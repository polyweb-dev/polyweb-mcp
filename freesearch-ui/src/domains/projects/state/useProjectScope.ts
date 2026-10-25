import { useContext } from "react"
import { ProjectScopeContext } from "./context"
import type { ProjectScopeContextValue } from "./context"

/** Return the project scope, or reject a component outside its provider. */
export function useProjectScope(): ProjectScopeContextValue {
  const value = useContext(ProjectScopeContext)
  if (value === undefined) {
    throw new Error("useProjectScope must be used inside ProjectScopeProvider")
  }
  return value
}
