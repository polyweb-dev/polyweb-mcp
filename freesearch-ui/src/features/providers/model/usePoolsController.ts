import { useCallback, useState } from "react"
import { createPool, listPools, updatePool } from "@/domains/providers"
import type { Pool, PoolInput } from "@/domains/providers"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import type { ScopedResource } from "@/shared/lib/useScopedResource"
import { poolFailureMessage } from "./capacityMessages"

export interface PoolsController {
  pools: ScopedResource<Pool[]>
  pending: boolean
  formError: string | null
  /** Open pool form: `"new"`, the pool being edited, or `null`. */
  editing: Pool | "new" | null
  openForm: (target: Pool | "new" | null) => void
  /** Pool whose credential links are open, or `null`. */
  linksFor: Pool | null
  openLinks: (pool: Pool | null) => void
  save: (input: PoolInput) => Promise<boolean>
}

/** System pools: list, create, edit, and which pool's links are open. */
export function usePoolsController(scopeKey: string, enabled: boolean): PoolsController {
  const pools = useScopedResource({ scopeKey: `${scopeKey}:pools`, load: listPools, enabled })
  const reload = pools.reload
  const [pending, setPending] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [editing, setEditing] = useState<Pool | "new" | null>(null)
  const [linksFor, setLinksFor] = useState<Pool | null>(null)

  const openForm = useCallback((target: Pool | "new" | null) => {
    setFormError(null)
    setEditing(target)
  }, [])

  const save = useCallback(
    async (input: PoolInput) => {
      const target = editing
      if (target === null) return false
      setPending(true)
      setFormError(null)
      try {
        await (target === "new" ? createPool(input) : updatePool(target.id, input))
        setEditing(null)
        void reload()
        return true
      } catch (error) {
        setFormError(poolFailureMessage(error, "The pool could not be saved."))
        return false
      } finally {
        setPending(false)
      }
    },
    [editing, reload]
  )

  return { pools, pending, formError, editing, openForm, linksFor, openLinks: setLinksFor, save }
}
