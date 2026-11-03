import { useCallback, useState } from "react"
import { deletePoolLink, listPoolLinks, listSystemCredentials, putPoolLink } from "@/domains/providers"
import type { Pool, PoolLink, ProviderOperation, SystemCredential } from "@/domains/providers"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import type { ScopedResource, ScopedResourceState } from "@/shared/lib/useScopedResource"
import { poolFailureMessage } from "./capacityMessages"

export interface PoolLinksController {
  links: ScopedResource<PoolLink[]>
  /** System credentials of the pool's provider; an error when they are not readable. */
  credentials: ScopedResourceState<SystemCredential[]>
  pending: boolean
  message: string | null
  link: (credentialId: string, operation: ProviderOperation) => Promise<void>
  unlink: (link: PoolLink) => Promise<void>
}

/** Credential links of one pool. */
export function usePoolLinks(pool: Pool): PoolLinksController {
  const links = useScopedResource({
    scopeKey: `pool-links:${pool.id}`,
    load: (signal) => listPoolLinks(pool.id, signal),
  })
  const credentials = useScopedResource({
    scopeKey: `pool-credentials:${pool.providerType}`,
    load: async (signal) =>
      (await listSystemCredentials(signal)).filter((row) => row.providerType === pool.providerType),
  })
  const reload = links.reload
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const run = useCallback(
    async (action: () => Promise<unknown>, fallback: string) => {
      setPending(true)
      setMessage(null)
      try {
        await action()
        void reload()
      } catch (error) {
        setMessage(poolFailureMessage(error, fallback))
      } finally {
        setPending(false)
      }
    },
    [reload]
  )

  const link = useCallback(
    (credentialId: string, operation: ProviderOperation) =>
      run(() => putPoolLink(pool.id, credentialId, operation), "The credential could not be linked."),
    [run, pool.id]
  )

  const unlink = useCallback(
    (row: PoolLink) =>
      run(() => deletePoolLink(row.poolId, row.credentialId, row.operation), "The link could not be removed."),
    [run]
  )

  return { links, credentials, pending, message, link, unlink }
}
