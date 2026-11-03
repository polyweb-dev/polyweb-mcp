import { useCallback, useState } from "react"
import { useActionStatus } from "./useActionStatus"
import type { ActionStatus } from "./useActionStatus"
import { useCredentialForms } from "./useCredentialForms"
import type { CredentialForms } from "./useCredentialForms"
import {
  DELETE_FAILED_MESSAGE,
  DISCONNECT_FAILED_MESSAGE,
  credentialFailureMessage,
} from "./credentialMessages"
import type { CredentialRef, CredentialRoutes } from "./credentialRoutes"

export interface CredentialActions extends CredentialForms {
  status: ActionStatus
  deleting: CredentialRef | null
  requestDelete: (credential: CredentialRef | null) => void
  confirmDelete: () => Promise<void>
  /** Credential base path of the open Connect dialog, or `null`. */
  connectBase: string | null
  openConnect: (credential: CredentialRef | null) => void
  disconnect: (credential: CredentialRef) => Promise<void>
}

/**
 * Add, rotate, delete and OAuth connect of one credential list. Every
 * success reloads the owning list.
 */
export function useCredentialActions(routes: CredentialRoutes, reload: () => void): CredentialActions {
  const status = useActionStatus()
  const { begin, finish } = status
  const forms = useCredentialForms(routes, reload, status)
  const [deleting, setDeleting] = useState<CredentialRef | null>(null)
  const [connectBase, setConnectBase] = useState<string | null>(null)

  const runPageAction = useCallback(
    async (action: () => Promise<void>, fallback: string) => {
      begin()
      try {
        await action()
        finish()
        reload()
      } catch (error) {
        finish({ message: credentialFailureMessage(error, fallback) })
      }
    },
    [begin, finish, reload]
  )

  const confirmDelete = useCallback(async () => {
    const target = deleting
    setDeleting(null)
    if (target !== null) await runPageAction(() => routes.remove(target.id), DELETE_FAILED_MESSAGE)
  }, [deleting, routes, runPageAction])

  const disconnect = useCallback(
    (credential: CredentialRef) =>
      runPageAction(() => routes.disconnect(credential.id), DISCONNECT_FAILED_MESSAGE),
    [routes, runPageAction]
  )

  const openConnect = useCallback(
    (credential: CredentialRef | null) =>
      setConnectBase(credential === null ? null : routes.oauthBase(credential.id)),
    [routes]
  )

  return {
    ...forms,
    status,
    deleting,
    requestDelete: setDeleting,
    confirmDelete,
    connectBase,
    openConnect,
    disconnect,
  }
}
