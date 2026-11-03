import { useCallback, useMemo, useState } from "react"

/** Pending flag plus page-level failure and success text of one page. */
export interface ActionStatus {
  pending: boolean
  message: string | null
  notice: string | null
  /** Start one action: pending on, every text cleared. */
  begin: () => void
  /** Finish one action with an optional failure or success text. */
  finish: (result?: { message?: string; notice?: string }) => void
}

/** Shared status of the actions of one page. */
export function useActionStatus(): ActionStatus {
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const begin = useCallback(() => {
    setPending(true)
    setMessage(null)
    setNotice(null)
  }, [])

  const finish = useCallback((result?: { message?: string; notice?: string }) => {
    setPending(false)
    setMessage(result?.message ?? null)
    setNotice(result?.notice ?? null)
  }, [])

  return useMemo(
    () => ({ pending, message, notice, begin, finish }),
    [pending, message, notice, begin, finish]
  )
}
