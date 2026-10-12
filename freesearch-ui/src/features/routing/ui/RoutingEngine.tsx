import { PillTabs } from "@/shared/ui/PillTabs"
import { PillTabsList } from "@/shared/ui/PillTabsList"
import { PillTabsPanel } from "@/shared/ui/PillTabsPanel"
import { useFreeSearch } from "@/context/useFreeSearch"
import { RouteSimulator } from "./RouteSimulator"
import { RoutingStrategy } from "./RoutingStrategy"

const ROUTING_VIEW_OPTIONS = [
  { value: "strategy", label: "Strategy" },
  { value: "simulator", label: "Simulator" },
] as const

/** Routing workbench shell for arbitration and simulation controls. */
export function RoutingEngine() {
  const { routingError } = useFreeSearch()

  return (
    <PillTabs
      options={ROUTING_VIEW_OPTIONS}
      defaultValue="strategy"
      ariaLabel="Routing view"
      idPrefix="routing"
      className="flex flex-1 flex-col space-y-6"
    >
      <div className="flex flex-col justify-between gap-4 border-b border-[var(--border-subtle)] pb-2 sm:flex-row sm:items-center">
        <div>
          <h2 className="text-[var(--text-strong)]">Routing</h2>
          <p className="mt-0.5 text-[13px] text-[var(--muted)]">
            Dynamic provider arbitration and route simulation.
          </p>
        </div>

        <PillTabsList className="ml-auto" />
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
      <PillTabsPanel value="simulator" className="flex flex-1 flex-col pt-5">
        <RouteSimulator />
      </PillTabsPanel>
    </PillTabs>
  )
}
