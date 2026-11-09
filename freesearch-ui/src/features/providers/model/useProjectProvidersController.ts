import { useCallback } from "react"
import { getProjectProviderView } from "@/domains/providers"
import type { ProjectProviderView } from "@/domains/providers"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import type { ScopedResource } from "@/shared/lib/useScopedResource"

export interface ProjectProvidersController {
  view: ScopedResource<ProjectProviderView>
  reloadAll: () => void
}

/**
 * Provider view controller of one project.
 *
 * The read is bound to `accountId:projectId` so a project switch drops any
 * late answer.
 */
export function useProjectProvidersController(options: {
  accountId: string
  projectId: string
}): ProjectProvidersController {
  const { accountId, projectId } = options
  const scopeKey = `${accountId}:${projectId}`
  const view = useScopedResource({
    scopeKey: `${scopeKey}:providers`,
    load: (signal) => getProjectProviderView(projectId, signal),
  })
  const reloadViewResource = view.reload
  const reloadAll = useCallback(() => {
    void reloadViewResource()
  }, [reloadViewResource])
  return { view, reloadAll }
}
