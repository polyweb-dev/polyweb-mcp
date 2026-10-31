import { useMemo } from "react"
import type { ReactNode } from "react"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import type { ScopedResourceState } from "@/shared/lib/useScopedResource"
import { getProjectAccess } from "../api/projectsApi"
import type { ProjectAccess } from "../model/types"
import { ProjectScopeContext } from "./context"
import type { ProjectScopeContextValue } from "./context"
import { useProjects } from "./useProjects"

/** Live re-check cadence of one open project: every 30 seconds and on focus. */
const ACCESS_POLL_MS = 30_000

/**
 * Scope-bound owner of one project's access state.
 *
 * The access state is keyed by `accountId:projectId`: a project switch aborts
 * the old read, drops its late result, and shows `loading` at once, so one
 * project's permissions never appear under another. A `null` project (a
 * global route) provides no scope and sends no request. Inside one scope, the
 * live access poll keeps role changes fresh without caching.
 */
export function ProjectScopeProvider({
  accountId,
  projectId,
  children,
}: {
  accountId: string
  projectId: string | null
  children: ReactNode
}) {
  const { projects } = useProjects()
  const resource = useScopedResource<ProjectAccess>({
    scopeKey: `${accountId}:${projectId ?? ""}`,
    load: (signal) => getProjectAccess(projectId ?? "", signal),
    pollMs: ACCESS_POLL_MS,
    enabled: projectId !== null,
  })

  const accessState = useMemo<ScopedResourceState<ProjectAccess>>(() => {
    if (resource.status === "ready") return { status: "ready", data: resource.data }
    if (resource.status === "error") return { status: "error", error: resource.error }
    return { status: "loading" }
  }, [resource])

  const value = useMemo<ProjectScopeContextValue | undefined>(() => {
    if (projectId === null) return undefined
    return {
      projectId,
      project: projects.find((project) => project.id === projectId) ?? null,
      accessState,
      refreshAccess: resource.reload,
    }
  }, [projectId, projects, accessState, resource.reload])

  return <ProjectScopeContext.Provider value={value}>{children}</ProjectScopeContext.Provider>
}
