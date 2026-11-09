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

/**
 * Return the open project scope, or `null` on a global route.
 *
 * Shell chrome such as the sidebar project group renders on every route, so
 * it uses this variant instead of rejecting a missing scope.
 */
export function useProjectScopeOptional(): ProjectScopeContextValue | null {
  return useContext(ProjectScopeContext) ?? null
}
