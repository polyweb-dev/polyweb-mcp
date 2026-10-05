import {
  deriveProviderAttempts,
  type TraceDetail,
  type TraceOutput,
  type TraceProviderAttempt,
} from "@/domains/activity"
import { Button } from "@/shared/ui/button"
import { Modal } from "@/shared/ui/Modal"
import { TraceDetailError } from "./TraceDetailError"
import { TraceDetailSection } from "./TraceDetailSection"
import { TraceDetailSummary } from "./TraceDetailSummary"
import type { RankingMode } from "./TraceRankingExplanation"
import { TraceInspectionWorkspace } from "./TraceInspectionWorkspace"

export interface TraceDetailDialogProps {
  trace: TraceDetail | null
  isOpen: boolean
  status: "loading" | "ready" | "error"
  error: string | null
  /** Provider span this dialog is scoped to; null shows the whole trace. */
  providerSpanId?: string | null
  onClose: () => void
  onRetry: () => void
}

/** Provider-scoped view reads the attempt's own results as a search output. */
function scopedOutput(trace: TraceDetail, spanId: string | null): TraceOutput | null {
  const attempt = deriveProviderAttempts(trace.stages, trace.provider).find(
    (candidate) => candidate.spanId === spanId
  )
  if (attempt === undefined) return trace.output
  return { kind: "search_results", query: trace.input ?? "", results: attempt.results }
}

function attemptFor(trace: TraceDetail, spanId: string | null): TraceProviderAttempt | null {
  if (spanId === null) return null
  return (
    deriveProviderAttempts(trace.stages, trace.provider).find(
      (candidate) => candidate.spanId === spanId
    ) ?? null
  )
}

interface ReadyViewOptions {
  trace: TraceDetail
  attempt: TraceProviderAttempt | null
  providerSpanId: string | null
}

/** The decoded part of the detail: rail, failure, query, inspection workspace. */
function readyView({ trace, attempt, providerSpanId }: ReadyViewOptions) {
  // Only a fused fanout is ranking across providers; a single-provider trace
  // (or one provider picked out of a fanout) shows that provider's own order.
  const mode: RankingMode =
    attempt !== null || trace.provider !== "aggregated" ? "provider" : "fusion"
  return (
    // Exactly the height of the scrolling body, so the workspace below the rail
    // and the query can be handed what is left and share it. The height must be
    // definite: with `min-h-full` the leftover is indefinite and the workspace
    // falls back to its content, which pushes the panes out of the dialog.
    <div className="flex h-full min-h-0 min-w-0 flex-col gap-2.5 text-[13px]">
      <div className="grid min-w-0 shrink-0 gap-2 sm:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] sm:items-stretch">
        <TraceDetailSection title={trace.operation === "fetch" ? "URL" : "Query"}>
          <p
            title={trace.input ?? "—"}
            className="m-0 mono max-h-12 overflow-y-auto text-[12px] leading-[18px] text-[var(--text)] whitespace-pre-wrap [overflow-wrap:anywhere]"
          >
            {trace.input ?? "—"}
          </p>
        </TraceDetailSection>
        <TraceDetailSummary trace={trace} attempt={attempt} />
      </div>
      <TraceDetailError trace={trace} />

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <TraceInspectionWorkspace
          key={`${trace.traceId}:${providerSpanId ?? "all"}`}
          trace={trace}
          output={scopedOutput(trace, providerSpanId)}
          attempt={attempt}
          mode={mode}
        />
      </div>
    </div>
  )
}

/**
 * Trace detail. Fixed header and a vertically scrolling body: one telemetry
 * rail, the query, and one inspection workspace that holds the recorded results
 * and the recorded trajectory with the selected payload at its side. Scoped to
 * a provider attempt, both views show that attempt's response instead (PLAN §5).
 */
export function TraceDetailDialog({
  trace,
  isOpen,
  status,
  error,
  providerSpanId = null,
  onClose,
  onRetry,
}: TraceDetailDialogProps) {
  if (!isOpen) return null
  const attempt = trace === null ? null : attemptFor(trace, providerSpanId)

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Trace detail"
      subtitle="Stored in this FreeSearch database; query and results are shown only here."
      maxWidth="7xl"
      scrollBody
    >
      {status === "loading" && (
        <p className="text-[13px] text-[var(--muted)]" role="status">
          Loading trace detail...
        </p>
      )}

      {status === "error" && (
        <div className="space-y-3">
          <p role="alert" className="text-[13px]" style={{ color: "var(--status-danger)" }}>
            Trace detail unavailable — {error}
          </p>
          <Button variant="outline" size="sm" onClick={onRetry}>
            Retry
          </Button>
        </div>
      )}

      {status === "ready" && trace !== null && readyView({ trace, attempt, providerSpanId })}
    </Modal>
  )
}
