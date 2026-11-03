import { useCallback, useMemo } from "react"
import {
  CREDENTIAL_OPERATIONS,
  createBinding,
  deleteBinding,
  getProjectProviderView,
  listProjectCredentials,
  setBindingOperations,
} from "@/domains/providers"
import type {
  NewBindingInput,
  ProjectCredential,
  ProjectProviderView,
  ProviderBinding,
  ProviderOperation,
} from "@/domains/providers"
import { isForbidden } from "@/shared/api/conflict"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import type { ScopedResource } from "@/shared/lib/useScopedResource"
import { PERMISSION_DENIED_MESSAGE } from "./credentialMessages"
import { projectCredentialRoutes } from "./credentialRoutes"
import { useActionStatus } from "./useActionStatus"
import type { ActionStatus } from "./useActionStatus"
import { useCredentialActions } from "./useCredentialActions"
import type { CredentialActions } from "./useCredentialActions"

export const NEW_BINDING_NOTICE = "New bindings start turned off. Turn on search or fetch to use it."

export interface ProjectProvidersController {
  view: ScopedResource<ProjectProviderView>
  /** Project-facing credentials by id (management flag and generation). */
  credentialsById: ReadonlyMap<string, ProjectCredential>
  bindingStatus: ActionStatus
  credentialActions: CredentialActions
  addBinding: (input: NewBindingInput) => Promise<boolean>
  toggleOperation: (binding: ProviderBinding, operation: ProviderOperation, on: boolean) => Promise<void>
  removeBinding: (binding: ProviderBinding) => Promise<void>
  reloadAll: () => void
}

function bindingFailure(error: unknown, fallback: string): string {
  return isForbidden(error) ? PERMISSION_DENIED_MESSAGE : fallback
}

/**
 * Provider view controller of one project.
 *
 * Both reads are bound to `accountId:projectId`: a project switch aborts them
 * and drops any late answer, and the page remounts with the scope so dialogs,
 * drafts and secrets of the previous project are gone.
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
  const credentials = useScopedResource({
    scopeKey: `${scopeKey}:credentials`,
    load: (signal) => listProjectCredentials(projectId, signal),
  })
  const reloadView = view.reload
  const reloadCredentials = credentials.reload
  const reloadAll = useCallback(() => {
    void reloadView()
    void reloadCredentials()
  }, [reloadView, reloadCredentials])
  const routes = useMemo(() => projectCredentialRoutes(projectId), [projectId])
  const credentialActions = useCredentialActions(routes, reloadAll)
  const bindingStatus = useActionStatus()
  const { begin, finish } = bindingStatus

  const credentialsById = useMemo(
    () =>
      new Map(credentials.status === "ready" ? credentials.data.map((row) => [row.id, row]) : []),
    [credentials]
  )

  const runBinding = useCallback(
    async (action: () => Promise<unknown>, fallback: string, notice?: string) => {
      begin()
      try {
        await action()
        finish(notice === undefined ? undefined : { notice })
        void reloadView()
        return true
      } catch (error) {
        finish({ message: bindingFailure(error, fallback) })
        return false
      }
    },
    [begin, finish, reloadView]
  )

  const addBinding = useCallback(
    (input: NewBindingInput) =>
      runBinding(() => createBinding(projectId, input), "The binding could not be created.", NEW_BINDING_NOTICE),
    [runBinding, projectId]
  )

  const toggleOperation = useCallback(
    async (binding: ProviderBinding, operation: ProviderOperation, on: boolean) => {
      const next = CREDENTIAL_OPERATIONS.filter((entry) =>
        entry === operation ? on : binding.enabledOperations.includes(entry)
      )
      await runBinding(
        () => setBindingOperations(projectId, binding.id, next),
        "The binding could not be changed."
      )
    },
    [runBinding, projectId]
  )

  const removeBinding = useCallback(
    async (binding: ProviderBinding) => {
      await runBinding(() => deleteBinding(projectId, binding.id), "The binding could not be removed.")
    },
    [runBinding, projectId]
  )

  return {
    view,
    credentialsById,
    bindingStatus,
    credentialActions,
    addBinding,
    toggleOperation,
    removeBinding,
    reloadAll,
  }
}
