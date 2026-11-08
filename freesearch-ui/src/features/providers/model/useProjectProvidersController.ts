import { useCallback, useMemo } from "react"
import { getProjectProviderView } from "@/domains/providers"
import type { ProjectCredential, ProjectProviderView } from "@/domains/providers"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import type { ScopedResource } from "@/shared/lib/useScopedResource"
import { projectCredentialRoutes } from "./credentialRoutes"
import { useActionStatus } from "./useActionStatus"
import type { ActionStatus } from "./useActionStatus"
import type { BindingActions } from "./useBindingActions"
import { useCredentialActions } from "./useCredentialActions"
import type { CredentialActions } from "./useCredentialActions"

export interface ProjectProvidersController extends BindingActions {
  view: ScopedResource<ProjectProviderView>
  /** Project-facing keys by id (management flag and generation). */
  credentialsById: ReadonlyMap<string, ProjectCredential>
  bindingStatus: ActionStatus
  credentialActions: CredentialActions
  reloadAll: () => void
}

/**
 * Provider view controller of one project.
 *
 * The read is bound to `accountId:projectId` so a project switch drops any
 * late answer. Binding writes stay unavailable until a replacement exists.
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
  const bindingActions = useMemo<BindingActions>(() => ({
    addBinding: async () => false,
    removeBinding: async () => {},
    toggleOperation: async () => {
      bindingStatus.finish({ message: "Changing provider operations is not available yet." })
    },
  }), [bindingStatus])
  const credentialsById = useMemo(() => new Map<string, ProjectCredential>(), [])

  return { view, credentialsById, bindingStatus, credentialActions, reloadAll, ...bindingActions }
}
