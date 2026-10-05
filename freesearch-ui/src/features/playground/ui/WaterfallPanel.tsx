import type { ProviderWaterfallItem } from "@/domains/execution"
import { providerIdentity } from "@/domains/providers"
import { ProviderBadge } from "@/shared/ui/ProviderBadge"
import {
  LatencyWaterfall,
  LatencyWaterfallValue,
  type LatencyWaterfallRow,
} from "@/shared/ui/LatencyWaterfall"

const OUTCOME_COLORS: Record<ProviderWaterfallItem["status"], string> = {
  success: "var(--signal)",
  failed: "var(--status-danger)",
  rate_limited: "var(--status-warning)",
  skipped: "var(--muted)",
}

function axisTotal(waterfall: readonly ProviderWaterfallItem[]): number {
  if (waterfall.length === 0) return 1
  return Math.max(1, ...waterfall.map((item) => item.latencyMs))
}

function toRow(item: ProviderWaterfallItem): LatencyWaterfallRow {
  const identity = providerIdentity(item.providerId)
  const succeeded = item.status === "success"
  return {
    id: item.providerId,
    label: (
      <ProviderBadge
        providerId={identity.id}
        name={identity.name}
        className="text-[12px] font-medium text-[var(--text)]"
        logoClassName="size-3.5"
      />
    ),
    // Execution rows carry no span offsets: the fan-out starts each provider at
    // the request, so every lane begins at zero on the shared axis.
    segments: [{ offsetMs: 0, durationMs: item.latencyMs, color: OUTCOME_COLORS[item.status] }],
    value: (
      <LatencyWaterfallValue
        durationMs={item.latencyMs}
        resultCount={succeeded ? item.resultsCount : null}
        outcome={succeeded ? undefined : item.status}
      />
    ),
  }
}

/** Waterfall latency diagnostics for the executed provider fan-out. */
export function WaterfallPanel({ waterfall }: { waterfall: ProviderWaterfallItem[] }) {
  const hasDetailedTrace = waterfall.length > 1

  return (
    <div className="min-w-0 space-y-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 text-[13px]">
        <span className="font-medium text-[var(--text-strong)]">Execution waterfall</span>
        {hasDetailedTrace && (
          <span className="text-[12px] text-[var(--muted)]">Live execution trace</span>
        )}
      </div>

      <LatencyWaterfall
        rows={waterfall.map(toRow)}
        totalMs={axisTotal(waterfall)}
        ariaLabel="Provider latency waterfall"
      />
    </div>
  )
}
