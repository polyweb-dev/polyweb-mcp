import React from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
import type { RoutingPreset } from "@/types/freesearch"
import { getEligibleProviders } from "./routingUtils"
import { cn } from "@/lib/utils"

interface StrategyCard {
  id: RoutingPreset
  label: string
  badge: string
  description: string
}

const STRATEGY_CARDS: StrategyCard[] = [
  {
    id: "priority",
    label: "Strict priority",
    badge: "Manual ordering",
    description: "Routes to P1 provider first, cascades down user-defined ranks.",
  },
  {
    id: "cost_optimized",
    label: "Cost optimized",
    badge: "Zero-cost bias",
    description: "Prefers keyless tiers and free allotments before paid credits.",
  },
  {
    id: "latency_optimized",
    label: "Latency optimized",
    badge: "Fastest response",
    description: "Routes to the provider with lowest p95 roundtrip.",
  },
  {
    id: "quality_first",
    label: "Quality first",
    badge: "Rich extraction",
    description: "Prefers neural search and deep LLM extractors.",
  },
]

/**
 * Strategy selection: one radio-styled card per routing preset, previewing the
 * provider the active strategy would promote to primary.
 */
export const RoutingStrategy: React.FC = () => {
  const {
    providers,
    routingPreset,
    costOptimizationPreset,
    setRoutingPreset,
    updateCostPreset,
  } = useFreeSearch()

  const handleSelect = (card: StrategyCard) => {
    if (card.id === "cost_optimized") {
      const nextPreset = costOptimizationPreset === "free_first" ? "balanced" : "free_first"
      setRoutingPreset(nextPreset === "free_first" ? card.id : "priority")
      void updateCostPreset(nextPreset)
      return
    }
    setRoutingPreset(card.id)
  }

  return (
    <section className="space-y-3 max-w-3xl">
      <div className="flex items-center justify-between">
        <h3 className="text-[var(--text-strong)]">Active algorithm</h3>
      </div>

      <div className="space-y-2">
        {STRATEGY_CARDS.map((card) => (
          <StrategyCardButton
            key={card.id}
            card={card}
            isSelected={
               card.id === "cost_optimized"
                 ? costOptimizationPreset === "free_first"
                 : routingPreset === card.id
             }
            onSelect={() => handleSelect(card)}
            providers={providers}
          />
        ))}
      </div>
    </section>
  )
}

interface StrategyCardButtonProps {
  card: StrategyCard
  isSelected: boolean
  onSelect: () => void
  providers: ReturnType<typeof useFreeSearch>["providers"]
}

const StrategyCardButton: React.FC<StrategyCardButtonProps> = ({
  card,
  isSelected,
  onSelect,
  providers,
}) => {
  const primary = isSelected ? getEligibleProviders(providers, "search", card.id)[0] : undefined

  return (
    <button
      type="button"
      aria-pressed={isSelected}
      onClick={onSelect}
      className={cn(
        "w-full text-left p-3.5 rounded-lg border transition-all flex items-start gap-3.5 motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--surface)]",
        isSelected
          ? "bg-[var(--signal-muted)] border-[var(--signal)]"
          : "bg-transparent border-[var(--border-subtle)] hover:bg-[var(--elevated)]"
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "mt-0.5 w-4 h-4 rounded-full border-2 flex items-center justify-center shrink-0 transition-colors",
          isSelected ? "border-[var(--signal)]" : "border-[var(--border-subtle)]"
        )}
      >
        {isSelected && (
          <span className="w-2 h-2 rounded-full bg-[var(--signal)]" />
        )}
      </span>

      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <span
            className={cn(
              "text-[13px] font-medium",
              isSelected ? "text-[var(--text-strong)]" : "text-[var(--text)]"
            )}
          >
            {card.label}
          </span>
          <span className="text-[12px] px-2 py-0.5 rounded text-[var(--muted)] bg-[var(--elevated)] whitespace-nowrap">
            {card.badge}
           </span>
           {card.id !== "cost_optimized" && (
             <span className="text-[12px] px-2 py-0.5 rounded text-[var(--muted)] bg-[var(--elevated)] whitespace-nowrap">
               Simulation view only
             </span>
           )}

        </div>
        <p className="text-[13px] mt-1 text-[var(--muted)] leading-relaxed">
          {card.description}
        </p>

        {primary && (
          <div className="mt-2.5 pt-2.5 border-t border-[var(--border-subtle)] flex items-center gap-2">
            <span className="text-[12px] px-1.5 py-0.5 rounded bg-[var(--signal-muted)] text-[var(--signal)] font-medium">
              Primary
            </span>
            <span className="text-[13px] text-[var(--text-strong)]">{primary.name}</span>
            <span className="text-[13px] text-[var(--muted)] tnum ml-auto">
              {primary.latencyP95Ms === null ? "—" : `${primary.latencyP95Ms} ms`} p95
            </span>
          </div>
        )}
      </div>
    </button>
  )
}
