import type { ProviderWaterfallItem } from "@/domains/execution"
import { LatencyWaterfall, type LatencyWaterfallRow } from "@/shared/ui/LatencyWaterfall"

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

function outcomeLabel(item: ProviderWaterfallItem): string {
  return item.status === "success" ? `${item.resultsCount} res` : item.status
}

function toRow(item: ProviderWaterfallItem): LatencyWaterfallRow {
  return {
    id: item.providerId,
    label: <span className="font-medium text-[var(--text)]">{item.providerName}</span>,
    // Execution rows carry no span offsets: the fan-out starts each provider at
    // the request, so every lane begins at zero on the shared axis.
    segments: [{ offsetMs: 0, durationMs: item.latencyMs, color: OUTCOME_COLORS[item.status] }],
    value: (
      <span className="tnum">
        <span className="text-[var(--text-strong)]">{item.latencyMs}ms</span>
        <span className="ml-2 text-[12px] text-[var(--muted)]">{outcomeLabel(item)}</span>
      </span>
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
        <span className="text-[12px] text-[var(--muted)]">
          {hasDetailedTrace ? "Live execution trace" : "Trace unavailable from backend"}
        </span>
      </div>

      <LatencyWaterfall
        rows={waterfall.map(toRow)}
        totalMs={axisTotal(waterfall)}
        ariaLabel="Provider latency waterfall"
      />
    </div>
  )
}
