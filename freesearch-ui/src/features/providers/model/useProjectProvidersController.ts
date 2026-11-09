import { useCallback, useMemo } from "react"
import { getProjectProviderView } from "@/domains/providers"
import type { ManagedProjectKey, ProjectProviderView } from "@/domains/providers"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import type { ScopedResource } from "@/shared/lib/useScopedResource"
import { projectCredentialRoutes } from "./credentialRoutes"
import { useActionStatus } from "./useActionStatus"
import type { ActionStatus } from "./useActionStatus"
import { useCredentialActions } from "./useCredentialActions"
import type { CredentialActions } from "./useCredentialActions"

export interface ProjectProvidersController {
  view: ScopedResource<ProjectProviderView>
  /** Project-facing keys by id (management flag and generation). */
  credentialsById: ReadonlyMap<string, ManagedProjectKey>
  bindingStatus: ActionStatus
  credentialActions: CredentialActions
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
  const routes = useMemo(() => projectCredentialRoutes(), [])
  const credentialActions = useCredentialActions(routes, reloadAll)
  const bindingStatus = useActionStatus()
  const credentialsById = useMemo(() => new Map<string, ManagedProjectKey>(), [])

  return { view, credentialsById, bindingStatus, credentialActions, reloadAll }
}
