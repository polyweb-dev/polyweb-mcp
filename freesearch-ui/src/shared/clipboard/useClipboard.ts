import { useCallback, useEffect, useRef, useState } from "react"

export interface UseClipboardOptions {
  /**
   * Auto-reset delay in ms for transient feedback (playground: 2000). Omit
   * for sticky feedback retained until reset() (OAuth pairing code).
   */
  resetAfterMs?: number
  /**
   * Legacy transient compat: show copied feedback even when the write fails
   * (useResultPreview fire-and-forget semantics). New call sites must leave
   * this unset; removal is a separate fix, not this slice.
   */
  optimistic?: boolean
}

export interface UseClipboard {
  copied: boolean
  /**
   * Writes text and reports the outcome: true on success, false when the
   * Clipboard API is missing or the write rejects (never throws). Sets
   * copied feedback on success — or unconditionally with optimistic.
   */
  copy: (text: string) => Promise<boolean>
  /** Clears any pending auto-reset timer and clears the flag. */
  reset: () => void
}

/**
 * Shared clipboard feedback for both legacy modes: transient auto-reset
 * (features/playground/model/useResultPreview.ts) and sticky retention with
 * availability/rejection silence (no auto-reset option).
 * Repeat copies restart the reset window; timers die on reset and unmount.
 */
export function useClipboard(options?: UseClipboardOptions): UseClipboard {
  const resetAfterMs = options?.resetAfterMs
  const optimistic = options?.optimistic === true
  const [copied, setCopied] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearTimer = useCallback(() => {
    if (timer.current !== null) {
      clearTimeout(timer.current)
      timer.current = null
    }
  }, [])

  useEffect(() => clearTimer, [clearTimer])

  const markCopied = useCallback(() => {
    setCopied(true)
    if (resetAfterMs !== undefined) {
      clearTimer()
      timer.current = setTimeout(() => {
        timer.current = null
        setCopied(false)
      }, resetAfterMs)
    }
  }, [resetAfterMs, clearTimer])

  const copy = useCallback(
    async (text: string): Promise<boolean> => {
      if (typeof navigator === "undefined" || !navigator.clipboard) return false
      let ok = true
      try {
        await navigator.clipboard.writeText(text)
      } catch {
        ok = false
      }
      if (ok || optimistic) markCopied()
      return ok
    },
    [optimistic, markCopied]
  )

  const reset = useCallback(() => {
    clearTimer()
    setCopied(false)
  }, [clearTimer])

  return { copied, copy, reset }
}
