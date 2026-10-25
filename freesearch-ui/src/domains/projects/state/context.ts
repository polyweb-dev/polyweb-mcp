import { createContext } from "react"
import type { ScopedResourceState } from "@/shared/lib/useScopedResource"
import type {
  Project,
  ProjectAccess,
  ProjectRolloutState,
  SystemAccess,
} from "../model/types"

/** Visibility of the projects surface inside the workspace. */
export type ProjectsAvailability = "loading" | "available" | "unavailable"

/**
 * Account-scope projects surface: the live system access descriptor and the
 * readable project list. `unavailable` hides the entire project UI.
 */
export interface ProjectsContextValue {
  accountId: string
  availability: ProjectsAvailability
  rolloutState: ProjectRolloutState | null
  systemAccess: SystemAccess | null
  projects: Project[]
  /** Re-load the list; resolves to the fresh list, or `null` when it fails. */
  reloadProjects: () => Promise<Project[] | null>
}

export const ProjectsContext = createContext<ProjectsContextValue | undefined>(undefined)

/**
 * Fallback value for surfaces that render where the provider may be absent.
 * `unavailable` hides the project UI, which matches the no-provider case.
 */
export const PROJECTS_UNAVAILABLE: ProjectsContextValue = {
  accountId: "",
  availability: "unavailable",
  rolloutState: null,
  systemAccess: null,
  projects: [],
  reloadProjects: () => Promise.resolve(null),
}

/**
 * Project-scope surface: the live access descriptor of the signed-in account
 * inside one project, plus the list copy of that project when present.
 */
export interface ProjectScopeContextValue {
  projectId: string
  project: Project | null
  accessState: ScopedResourceState<ProjectAccess>
  refreshAccess: () => void
}

export const ProjectScopeContext = createContext<ProjectScopeContextValue | undefined>(
  undefined
)
