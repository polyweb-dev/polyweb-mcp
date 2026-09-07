import React from "react"
import { Minus, Plus } from "lucide-react"
import { useFreeSearch } from "@/context/useFreeSearch"

const MIN_DEPTH = 1
const MAX_DEPTH = 5
/**
 * Resilience policy rows: persisted max-attempts depth and backend timeout disclosure.
 */
export const ResiliencePolicy: React.FC = () => {
  const { fallbackConfig, updateFallbackConfig } = useFreeSearch()

  const setDepth = (next: number) => {
    updateFallbackConfig({ maxAttempts: Math.min(MAX_DEPTH, Math.max(MIN_DEPTH, next)) })
  }

  return (
    <section className="space-y-3 max-w-3xl">
      <div>
        <h3 className="text-[var(--text-strong)]">Resilience policy</h3>
        <p className="text-[13px] text-[var(--muted)] mt-0.5">
          How far a failed route may cascade before the request gives up.
        </p>
      </div>

      <div className="rounded-lg border border-[var(--border-subtle)] px-4 divide-y divide-[var(--border-subtle)]">
        <div className="flex items-center justify-between py-3 gap-4">
          <div className="flex flex-col gap-0.5">
            <span className="text-[13px] text-[var(--muted)]">Cascade depth</span>
            <span className="text-[12px] text-[var(--muted)]">
              Max attempts are persisted for backend use; dispatch is currently single-attempt.
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              aria-label="Decrease cascade depth"
              onClick={() => setDepth(fallbackConfig.maxAttempts - 1)}
              disabled={fallbackConfig.maxAttempts <= MIN_DEPTH}
              className="p-1 rounded border border-[var(--border-subtle)] text-[var(--muted)] hover:text-[var(--text-strong)] transition-colors disabled:opacity-30 motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--surface)]"
            >
              <Minus className="size-3.5" />
            </button>
            <span className="text-[13px] text-[var(--text)] min-w-[140px] text-right tnum">
              {fallbackConfig.enabled
                ? `Up to ${fallbackConfig.maxAttempts} fallback hops`
                : "1 hop (single-shot)"}
            </span>
            <button
              type="button"
              aria-label="Increase cascade depth"
              onClick={() => setDepth(fallbackConfig.maxAttempts + 1)}
              disabled={fallbackConfig.maxAttempts >= MAX_DEPTH}
              className="p-1 rounded border border-[var(--border-subtle)] text-[var(--muted)] hover:text-[var(--text-strong)] transition-colors disabled:opacity-30 motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--surface)]"
            >
              <Plus className="size-3.5" />
            </button>
          </div>
        </div>

        <div className="flex items-center justify-between py-3 gap-4">
          <span className="text-[13px] text-[var(--muted)]">Hop timeout budget</span>
          {/* GAP: 10 — the backend does not expose a per-hop timeout budget. */}
          <span className="text-[13px] text-[var(--muted)]">Timeout budget not exposed by backend</span>
        </div>

      </div>
    </section>
  )
}
