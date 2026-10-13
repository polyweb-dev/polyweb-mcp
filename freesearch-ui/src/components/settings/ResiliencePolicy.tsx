import { Minus, Plus } from "lucide-react"
import { useFreeSearch } from "@/context/useFreeSearch"

const MIN_DEPTH = 1
const MAX_DEPTH = 5

/**
 * Resilience policy rows: persisted max-attempts depth and backend timeout disclosure.
 */
export function ResiliencePolicy() {
  const { fallbackConfig, updateFallbackConfig, canEditControls } = useFreeSearch()

  const setDepth = (next: number) => {
    updateFallbackConfig({ maxAttempts: Math.min(MAX_DEPTH, Math.max(MIN_DEPTH, next)) })
  }

  const depthValue = fallbackConfig.enabled
    ? "Up to " + fallbackConfig.maxAttempts + " fallback hops"
    : "1 hop (single-shot)"

  return (
    <div className="w-full max-w-none overflow-hidden rounded-lg border border-[var(--border-subtle)]">
      <div className="flex flex-col gap-2 border-b border-[var(--border-subtle)] bg-[var(--elevated)] px-4 py-2.5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2.5">
          <h3 className="text-[13px] font-semibold text-[var(--text-strong)]">
            Resilience policy
          </h3>
          <span className="rounded-full border border-[var(--border-subtle)] bg-[var(--surface)] px-2 py-0.5 text-[11px] text-[var(--muted)]">
            Cascade routing
          </span>
        </div>
        <p className="text-[12px] text-[var(--muted)]">
          How far a failed route may cascade before the request gives up.
        </p>
      </div>

      <div className="px-4 divide-y divide-[var(--border-subtle)]">
        <div className="flex items-center justify-between py-3 gap-4">
          <div className="flex flex-col gap-0.5">
            <span className="text-[13px] text-[var(--muted)]">Cascade depth</span>
            <span className="text-[12px] text-[var(--muted)]">
              Max attempts are persisted for backend use; dispatch is currently single-attempt.
            </span>
          </div>
          {canEditControls ? (
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
                {depthValue}
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
          ) : (
            // A role without control-edit access sees the current value only.
            <span className="text-[13px] text-[var(--text)] min-w-[140px] text-right tnum">
              {depthValue}
            </span>
          )}
        </div>

        <div className="flex items-center justify-between py-3 gap-4">
          <span className="text-[13px] text-[var(--muted)]">Hop timeout budget</span>
          {/* GAP: 10 — the backend does not expose a per-hop timeout budget. */}
          <span className="text-[13px] text-[var(--muted)]">Timeout budget not exposed by backend</span>
        </div>
      </div>
    </div>
  )
}
