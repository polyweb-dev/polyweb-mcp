import { useCallback, useState } from "react"
import { deleteCredentialGrant, listCredentialGrants, putCredentialGrant } from "@/domains/providers"
import type { CredentialGrant, ProviderOperation } from "@/domains/providers"
import { isForbidden } from "@/shared/api/conflict"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import type { ScopedResource } from "@/shared/lib/useScopedResource"

export interface CredentialGrantsController {
  grants: ScopedResource<CredentialGrant[]>
  pending: boolean
  message: string | null
  save: (projectId: string, operations: readonly ProviderOperation[]) => Promise<boolean>
  remove: (projectId: string) => Promise<void>
}

const SAVE_FAILED = "The grant could not be saved."
const REMOVE_FAILED = "The grant could not be removed."
const FORBIDDEN = "You do not have permission to change grants."

/** Project grants of one system credential. */
export function useCredentialGrants(credentialId: string): CredentialGrantsController {
  const grants = useScopedResource({
    scopeKey: `grants:${credentialId}`,
    load: (signal) => listCredentialGrants(credentialId, signal),
  })
  const reload = grants.reload
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const run = useCallback(
    async (action: () => Promise<unknown>, fallback: string) => {
      setPending(true)
      setMessage(null)
      try {
        await action()
        void reload()
        return true
      } catch (error) {
        setMessage(isForbidden(error) ? FORBIDDEN : fallback)
        return false
      } finally {
        setPending(false)
      }
    },
    [reload]
  )

  const save = useCallback(
    (projectId: string, operations: readonly ProviderOperation[]) =>
      run(() => putCredentialGrant(credentialId, projectId, operations), SAVE_FAILED),
    [run, credentialId]
  )

  const remove = useCallback(
    async (projectId: string) => {
      await run(() => deleteCredentialGrant(credentialId, projectId), REMOVE_FAILED)
    },
    [run, credentialId]
  )

  return { grants, pending, message, save, remove }
}
