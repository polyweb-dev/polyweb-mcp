import { useFreeSearch } from "@/context/useFreeSearch"
import type { RoutingPreset } from "@/types/freesearch"
import { getEligibleProviders } from "@/domains/routing"
import { ProviderLogo } from "@/components/common/ProviderLogo"
import { cn } from "@/lib/utils"

export interface StrategyCard {
  id: RoutingPreset
  label: string
  badge: string
  description: string
}

export interface StrategyCardButtonProps {
  card: StrategyCard
  isSelected: boolean
  onSelect: () => void
  providers: ReturnType<typeof useFreeSearch>["providers"]
}

/** One routing preset card with its promoted-primary preview. */
export function StrategyCardButton({
  card,
  isSelected,
  onSelect,
  providers,
}: StrategyCardButtonProps) {
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
          <div className="flex items-center gap-2">
            <span className="text-[12px] px-2 py-0.5 rounded text-[var(--muted)] bg-[var(--elevated)] whitespace-nowrap">
              {card.badge}
            </span>
            {card.id !== "cost_optimized" && (
              <span className="text-[12px] px-2 py-0.5 rounded text-[var(--muted)] bg-[var(--elevated)] whitespace-nowrap">
                Simulation view only
              </span>
            )}
          </div>
        </div>
        <p className="text-[13px] mt-1 text-[var(--muted)] leading-relaxed">
          {card.description}
        </p>

        {primary && (
          <div className="mt-2.5 pt-2.5 border-t border-[var(--border-subtle)] flex items-center gap-2">
            <span className="text-[12px] px-1.5 py-0.5 rounded bg-[var(--signal-muted)] text-[var(--signal)] font-medium">
              Primary
            </span>
            <ProviderLogo providerId={primary.id} />
            <span className="text-[13px] text-[var(--text-strong)]">{primary.name}</span>
            <span className="text-[13px] text-[var(--muted)] tnum ml-auto">
              {primary.latencyP95Ms === null ? "—" : primary.latencyP95Ms + " ms"} p95
            </span>
          </div>
        )}
      </div>
    </button>
  )
}
