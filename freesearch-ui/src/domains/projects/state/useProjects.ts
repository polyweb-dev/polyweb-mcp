import { useContext } from "react"
import { PROJECTS_UNAVAILABLE, ProjectsContext } from "./context"
import type { ProjectsContextValue } from "./context"

/** Return the projects surface, or reject a component outside its provider. */
export function useProjects(): ProjectsContextValue {
  const value = useContext(ProjectsContext)
  if (value === undefined) throw new Error("useProjects must be used inside ProjectsProvider")
  return value
}

/**
 * Return the projects surface or the `unavailable` fallback.
 *
 * Optional chrome such as the sidebar selector uses this variant: outside the
 * provider the project UI simply stays hidden, which keeps surfaces that mount
 * the sidebar standalone free of a provider requirement.
 */
export function useProjectsOptional(): ProjectsContextValue {
  return useContext(ProjectsContext) ?? PROJECTS_UNAVAILABLE
}
