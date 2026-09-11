import type { ProviderWaterfallItem } from "@/types/freesearch"

/** Waterfall latency diagnostics for the executed provider fan-out. */
export function WaterfallPanel({ waterfall }: { waterfall: ProviderWaterfallItem[] }) {
  return (
    <div className="p-4 rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] space-y-3">
      <div className="flex items-center justify-between text-[13px]">
        <span className="font-medium text-[var(--text-strong)]">Execution waterfall</span>
        <span className="text-[12px] text-[var(--muted)]">Trace unavailable from backend</span>
      </div>

      <div className="space-y-2">
        {waterfall.map((item) => {
          const maxLat = Math.max(...waterfall.map((w) => w.latencyMs)) || 100
          const widthPercent = Math.max(12, Math.round((item.latencyMs / maxLat) * 100))
          return (
            <div key={item.providerId} className="flex items-center gap-3 text-[13px]">
              <span className="w-24 truncate font-medium text-[var(--text)]">
                {item.providerName}
              </span>
              <div className="flex-1 rounded h-4 overflow-hidden bg-[var(--surface)] border border-[var(--border-subtle)]">
                <div
                  className="h-full flex items-center pl-1.5 text-[12px] font-medium text-white tnum transition-all duration-500"
                  style={{
                    width: widthPercent + "%",
                    background: item.status === "success" ? "var(--signal)" : "var(--status-danger)",
                  }}
                >
                  {item.latencyMs}ms
                </div>
              </div>
              <span className="text-[12px] w-16 text-right text-[var(--muted)] tnum">
                {item.status === "success" ? item.resultsCount + " res" : item.status}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
