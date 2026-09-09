import React from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
import type { RoutingPreset } from "@/types/freesearch"
import { StrategyCardButton } from "./StrategyCardButton"

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
    <section className="space-y-3 w-full max-w-none">
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

export { StrategyCardButton } from "./StrategyCardButton"
