import { useMemo, type ReactNode } from "react"
import {
  buildTraceStageTree,
  traceTrajectoryLabel,
  type TraceStage,
  type TraceStageNode,
} from "@/domains/activity"
import { LatencyWaterfall, type LatencyWaterfallRow } from "@/shared/ui/LatencyWaterfall"

export interface TraceTrajectoryProps {
  stages: readonly TraceStage[]
  totalMs: number
  selectedSpanId: string | null
  onSelect: (spanId: string) => void
}

const PROVIDER_SPAN_NAME = "freesearch.provider"
const TRACK_COLOR = "var(--accent-cyan)"
const PROCESSING_COLOR = "var(--accent-seafoam)"
const ERROR_COLOR = "var(--status-danger)"

/** Depth of every span inside the recorded hierarchy, keyed by span id. */
function depthById(stages: readonly TraceStage[]): ReadonlyMap<string, number> {
  const depths = new Map<string, number>()
  const walk = (nodes: readonly TraceStageNode[], depth: number) => {
    for (const node of nodes) {
      if (!depths.has(node.stage.spanId)) depths.set(node.stage.spanId, depth)
      walk(node.children, depth + 1)
    }
  }
  walk(buildTraceStageTree(stages), 0)
  return depths
}

function rowLabel(stage: TraceStage): ReactNode {
  const label = traceTrajectoryLabel(stage)
  return (
    <span className="block min-w-0">
      {/* The recorded stage stays announced even when the provider name
          replaces it on screen, so the row never loses its operation. */}
      {label !== stage.label && <span className="sr-only">{stage.label} </span>}
      <span className="[overflow-wrap:anywhere]">{label}</span>
      {stage.outcome !== "success" && (
        <span className="ml-1.5 text-[11px]" style={{ color: ERROR_COLOR }}>
          {stage.outcome}
        </span>
      )}
    </span>
  )
}

function trackColor(stage: TraceStage): string {
  if (stage.outcome === "error") return ERROR_COLOR
  if (stage.name === PROVIDER_SPAN_NAME) return TRACK_COLOR
  return PROCESSING_COLOR
}

/**
 * The recorded hierarchy and its timing in one list: every span once, in wire
 * order, indented by its depth, with its own offset/duration bar fused into the
 * row on the trace-wide scale (PLAN §5.4). Selecting a row hands its span id to
 * the side inspector; nothing here expands or animates.
 */
export function TraceTrajectory({
  stages,
  totalMs,
  selectedSpanId,
  onSelect,
}: TraceTrajectoryProps) {
  const depths = useMemo(() => depthById(stages), [stages])
  const rows: LatencyWaterfallRow[] = stages.map((stage) => ({
    id: stage.spanId,
    label: rowLabel(stage),
    segments: [{ offsetMs: stage.offsetMs, durationMs: stage.durationMs, color: trackColor(stage) }],
    value: `${stage.durationMs}ms`,
    depth: depths.get(stage.spanId) ?? 0,
    selected: stage.spanId === selectedSpanId,
    onSelect: () => onSelect(stage.spanId),
  }))

  return (
    <div className="min-w-0 max-h-[26rem] overflow-y-auto overflow-x-hidden pr-1">
      <LatencyWaterfall rows={rows} totalMs={totalMs} ariaLabel="Trace trajectory" />
    </div>
  )
}
