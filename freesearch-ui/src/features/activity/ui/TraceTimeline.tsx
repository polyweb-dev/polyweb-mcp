import type { TraceStage } from "@/domains/activity"
import { TraceStatusPill } from "./TraceStatusPill"

function stageColor(stage: TraceStage): string {
  if (stage.outcome === "error") return "var(--status-danger)"
  if (stage.outcome === "partial") return "var(--status-warning)"
  return "var(--signal)"
}

function percent(part: number, total: number): number {
  if (total <= 0) return 0
  return Math.min(100, Math.max(0, (part / total) * 100))
}

/**
 * Quiet vertical stage timeline. Each row is one span; the bar's offset is the
 * stage's start relative to the trace start, so concurrent fanout provider
 * spans visibly share a branch instead of pretending to be sequential.
 */
export function TraceTimeline({
  stages,
  totalMs,
}: {
  stages: TraceStage[]
  totalMs: number
}) {
  if (stages.length === 0) {
    return (
      <p className="text-[13px] text-[var(--muted)]">No stage timing was recorded.</p>
    )
  }
  return (
    <ol aria-label="Stage timeline" className="space-y-3">
      {stages.map((stage) => {
        const left = percent(stage.offsetMs, totalMs)
        const width = Math.max(2, percent(stage.durationMs, totalMs))
        return (
          <li key={stage.spanId} className="space-y-1">
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-[13px] text-[var(--text-strong)]">
                {stage.label}
                <span className="ml-2 text-[11px] text-[var(--muted)]">{stage.kind}</span>
              </span>
              <span className="flex items-baseline gap-2 text-[12px] text-[var(--muted)] tnum">
                {stage.outcome !== "success" && <TraceStatusPill outcome={stage.outcome} />}
                {stage.durationMs}ms
              </span>
            </div>
            <div
              className="relative h-1.5 w-full overflow-hidden rounded"
              style={{ background: "var(--surface)" }}
              aria-hidden="true"
            >
              <div
                className="absolute inset-y-0 rounded"
                style={{
                  left: `${left}%`,
                  width: `${Math.min(width, 100 - left)}%`,
                  background: stageColor(stage),
                }}
              />
            </div>
            {stage.error !== null && (
              <p className="text-[12px]" style={{ color: "var(--status-danger)" }}>
                {stage.error.type}: {stage.error.message}
              </p>
            )}
          </li>
        )
      })}
    </ol>
  )
}
