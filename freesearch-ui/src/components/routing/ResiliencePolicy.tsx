import React from "react"
import { Minus, Plus } from "lucide-react"
import { useFreeSearch } from "@/context/useFreeSearch"

const MIN_DEPTH = 1
const MAX_DEPTH = 5
const HOP_TIMEOUT_BUDGET_MS = "3,000 ms"

/**
 * Resilience policy rows: cascade depth stepper, hop timeout budget, and the
 * circuit breaker auto-bypass state.
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
          <span className="text-[13px] text-[var(--muted)]">Cascade depth</span>
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
          <span className="text-[13px] text-[var(--text)] tnum">{HOP_TIMEOUT_BUDGET_MS}</span>
        </div>

        <div className="flex items-center justify-between py-3 gap-4">
          <span className="text-[13px] text-[var(--muted)]">Circuit breaker auto-bypass</span>
          <span className="text-[13px] font-medium" style={{ color: "var(--status-healthy)" }}>
            Enabled
          </span>
        </div>
      </div>
    </section>
  )
}
