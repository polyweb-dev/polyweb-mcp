import { useState } from "react"
import type { ProjectPool } from "@/domains/projects"
import { updateKeyPool } from "@/domains/vault"
import type { PoolOperation } from "@/domains/vault"

export function usePoolOperation(reload: () => void) {
  const [change, setChange] = useState<{ pool: ProjectPool; operation: PoolOperation } | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const save = async (pool: ProjectPool, operation: PoolOperation, enabled: boolean) => {
    setPending(true)
    setError(null)
    try {
      const operations = enabled ? [...pool.operations, operation] : pool.operations.filter((entry) => entry !== operation)
      await updateKeyPool(pool.pool_id, { operations })
      setChange(null)
      reload()
    } catch {
      setError("The pool did not update. Try again.")
    } finally {
      setPending(false)
    }
  }
  const toggle = (pool: ProjectPool, operation: PoolOperation, enabled: boolean) => {
    setError(null)
    if (!enabled && pool.operations.length <= 1) setError("A pool must allow at least one operation.")
    else if (!enabled) setChange({ pool, operation })
    else void save(pool, operation, true)
  }
  return { change, pending, error, toggle, close: () => setChange(null),
    confirm: () => { if (change) void save(change.pool, change.operation, false) } }
}
