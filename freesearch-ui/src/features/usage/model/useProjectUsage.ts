import { useCallback } from "react"
import { getProjectUsage } from "@/domains/usage"
import type { ProjectUsage } from "@/domains/usage"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import type { ScopedResource } from "@/shared/lib/useScopedResource"

/**
 * Usage read of one project, keyed by `accountId:projectId`: a project switch
 * aborts the request and drops its late result.
 */
export function useProjectUsage(accountId: string, projectId: string): ScopedResource<ProjectUsage> {
  const load = useCallback((signal: AbortSignal) => getProjectUsage(projectId, signal), [projectId])
  return useScopedResource({ scopeKey: `${accountId}:${projectId}`, load })
}
