import React from "react"
import { ArrowDown, ArrowUp } from "lucide-react"
import type { ProviderConfig } from "@/types/freesearch"

export const PriorityIndicator: React.FC<{
  provider: ProviderConfig
  rank: number
  providerCount: number
  canMoveUp: boolean
  canMoveDown: boolean
  onMovePriority: (direction: "up" | "down") => void
}> = ({ provider, rank, providerCount, canMoveUp, canMoveDown, onMovePriority }) => (
  <div className="flex min-w-6 shrink-0 flex-col items-center gap-0.5">
    <button
      type="button"
      aria-label={`Move ${provider.name} priority up`}
      onClick={() => onMovePriority("up")}
      disabled={!canMoveUp}
      className="text-[var(--muted)] transition-colors hover:text-[var(--text-strong)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)]/40 disabled:cursor-not-allowed disabled:opacity-30 motion-reduce:transition-none"
    >
      <ArrowUp className="size-3" />
    </button>
    <span className="text-[12px] leading-none text-[var(--muted)] tnum" title={`Dispatch order ${rank} of ${providerCount}`}>
      P{rank}
    </span>
    <button
      type="button"
      aria-label={`Move ${provider.name} priority down`}
      onClick={() => onMovePriority("down")}
      disabled={!canMoveDown}
      className="text-[var(--muted)] transition-colors hover:text-[var(--text-strong)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)]/40 disabled:cursor-not-allowed disabled:opacity-30 motion-reduce:transition-none"
    >
      <ArrowDown className="size-3" />
    </button>
  </div>
)
