import React from "react"
import {
  PillTabs,
  PillTabsList,
  PillTabsPanel,
} from "@/components/common/PillTabs"
import { useFreeSearch } from "@/context/useFreeSearch"
import { ProviderRanks } from "./ProviderRanks"
import { ResiliencePolicy } from "./ResiliencePolicy"
import { RouteSimulator } from "./RouteSimulator"
import { RoutingStrategy } from "./RoutingStrategy"
import { getEligibleProviders } from "./routingUtils"

const ROUTING_VIEW_OPTIONS = [
  { value: "strategy", label: "Strategy" },
  { value: "simulator", label: "Simulator" },
  { value: "ranks", label: "Ranks" },
  { value: "resilience", label: "Resilience" },
] as const

/** Routing workbench shell for arbitration and resilience controls. */
export const RoutingEngine: React.FC = () => {
  const {
    providers,
    fallbackConfig,
    routingPreset,
    routingLoading,
    routingError,
  } = useFreeSearch()
  const eligible = getEligibleProviders(providers, "search", routingPreset)

  return (
    <PillTabs
      options={ROUTING_VIEW_OPTIONS}
      defaultValue="strategy"
      ariaLabel="Routing view"
      idPrefix="routing"
      className="space-y-6"
    >
      <div className="flex flex-col justify-between gap-4 border-b border-[var(--border-subtle)] pb-2 sm:flex-row sm:items-center">
        <div>
          <h2 className="text-[var(--text-strong)]">Routing</h2>
          <p className="mt-0.5 text-[13px] text-[var(--muted)]">
            Dynamic provider arbitration, priority ranking, and resilience controls.
          </p>
        </div>

        <div className="ml-auto flex flex-wrap items-center justify-end gap-4">
          <div className="flex items-center gap-4 text-[13px]">
            <span
              className="font-medium"
              style={{
                color: fallbackConfig.enabled
                  ? "var(--status-healthy)"
                  : "var(--muted)",
              }}
            >
              {!routingLoading && !routingError
                ? `Failover ${fallbackConfig.enabled ? "active" : "inactive"}`
                : null}
            </span>
            <span className="tnum text-[var(--muted)]">
              {eligible.length} of {providers.length} providers eligible
            </span>
          </div>
          <span
            aria-hidden="true"
            className="hidden h-5 w-px bg-[var(--border-subtle)] lg:block"
          />
          <PillTabsList className="ml-auto" />
        </div>
      </div>

      {routingError && (
        <p
          role="alert"
          className="rounded border border-[var(--status-danger)]/40 bg-[var(--elevated)] p-3 text-[13px]"
          style={{ color: "var(--status-danger)" }}
        >
          Routing configuration unavailable — {routingError}
        </p>
      )}

      <PillTabsPanel value="strategy" className="pt-5">
        <RoutingStrategy />
      </PillTabsPanel>
      <PillTabsPanel value="simulator" className="pt-5">
        <RouteSimulator />
      </PillTabsPanel>
      <PillTabsPanel value="ranks" className="pt-5">
        <ProviderRanks />
      </PillTabsPanel>
      <PillTabsPanel value="resilience" className="pt-5">
        <ResiliencePolicy />
      </PillTabsPanel>
    </PillTabs>
  )
}
