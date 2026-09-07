import React from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { getEligibleProviders } from "./routingUtils"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { RoutingStrategy } from "./RoutingStrategy"
import { RouteSimulator } from "./RouteSimulator"
import { ProviderRanks } from "./ProviderRanks"
import { ResiliencePolicy } from "./ResiliencePolicy"

/**
 * Routing workbench shell: live arbitration status plus the four routing
 * sub-workspaces (strategy, simulator, ranks, resilience).
 */
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
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-baseline justify-between gap-4 pb-2 border-b border-[var(--border-subtle)]">
        <div>
          <h2 className="text-[var(--text-strong)]">Routing</h2>
          <p className="text-[13px] text-[var(--muted)] mt-0.5">
            Dynamic provider arbitration, priority ranking, and resilience controls.
          </p>
        </div>

        <div className="flex items-center gap-4 text-[13px]">
          <span
            className="font-medium"
            style={{ color: fallbackConfig.enabled ? "var(--status-healthy)" : "var(--muted)" }}
          >
            {!routingLoading && !routingError
               ? `Failover ${fallbackConfig.enabled ? "active" : "inactive"}`
               : null}
          </span>
          <span className="text-[var(--muted)] tnum">
            {eligible.length} of {providers.length} providers eligible
          </span>
        </div>
      </div>

      {routingError && (
         <p
           role="alert"
           className="p-3 rounded border border-[var(--status-danger)]/40 bg-[var(--elevated)] text-[13px]"
           style={{ color: "var(--status-danger)" }}
         >
           Routing configuration unavailable — {routingError}
         </p>
       )}

       <Tabs defaultValue="strategy">
        <TabsList variant="line">
          <TabsTrigger value="strategy" className="text-[13px]">Strategy</TabsTrigger>
          <TabsTrigger value="simulator" className="text-[13px]">Simulator</TabsTrigger>
          <TabsTrigger value="ranks" className="text-[13px]">Ranks</TabsTrigger>
          <TabsTrigger value="resilience" className="text-[13px]">Resilience</TabsTrigger>
        </TabsList>

        <TabsContent value="strategy" className="pt-5">
          <RoutingStrategy />
        </TabsContent>
        <TabsContent value="simulator" className="pt-5">
          <RouteSimulator />
        </TabsContent>
        <TabsContent value="ranks" className="pt-5">
          <ProviderRanks />
        </TabsContent>
        <TabsContent value="resilience" className="pt-5">
          <ResiliencePolicy />
        </TabsContent>
      </Tabs>
    </div>
  )
}
