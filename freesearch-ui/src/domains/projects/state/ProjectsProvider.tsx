import { useCallback, useMemo } from "react"
import type { ReactNode } from "react"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import { getSystemAccess, listProjects } from "../api/projectsApi"
import type { Project, SystemAccess } from "../model/types"
import { ProjectsContext } from "./context"
import type { ProjectsContextValue } from "./context"

interface ProjectsSnapshot {
  system: SystemAccess
  list: Project[]
}

async function loadSnapshot(signal: AbortSignal): Promise<ProjectsSnapshot> {
  const [system, list] = await Promise.all([getSystemAccess(signal), listProjects(signal)])
  return { system, list }
}

/**
 * Account-scoped owner of the projects surface.
 *
 * The provider loads the live system access descriptor and the readable
 * project list once per account. A failed load resolves to `unavailable`,
 * which hides the entire project UI — this is the rollout gate of the web
 * client, and it is driven by the backend, never by the account role.
 */
export function ProjectsProvider({
  accountId,
  children,
}: {
  accountId: string
  children: ReactNode
}) {
  const resource = useScopedResource<ProjectsSnapshot>({
    scopeKey: accountId,
    load: loadSnapshot,
  })

  const reloadProjects = useCallback(async (): Promise<Project[] | null> => {
    const snapshot = await resource.reload()
    return snapshot?.list ?? null
  }, [resource.reload])

  const value = useMemo<ProjectsContextValue>(() => {
    const base = { accountId, reloadProjects }
    if (resource.status === "ready") {
      return {
        ...base,
        availability: "available",
        rolloutState: resource.data.system.rollout_state,
        systemAccess: resource.data.system,
        projects: resource.data.list,
      }
    }
    if (resource.status === "error") {
      return {
        ...base,
        availability: "unavailable",
        rolloutState: null,
        systemAccess: null,
        projects: [],
      }
    }
    return {
      ...base,
      availability: "loading",
      rolloutState: null,
      systemAccess: null,
      projects: [],
    }
  }, [accountId, resource, reloadProjects])

  return <ProjectsContext.Provider value={value}>{children}</ProjectsContext.Provider>
}
