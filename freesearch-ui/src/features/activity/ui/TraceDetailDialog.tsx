import {
  deriveProviderAttempts,
  type TraceDetail,
  type TraceOutput,
  type TraceProviderAttempt,
} from "@/domains/activity"
import { formatDateTime } from "@/shared/lib/formatTime"
import { Button } from "@/shared/ui/button"
import { Modal } from "@/shared/ui/Modal"
import { Tag } from "@/shared/ui/Tag"
import { TraceDetailError } from "./TraceDetailError"
import { TraceDetailSection } from "./TraceDetailSection"
import { TraceDetailSummary } from "./TraceDetailSummary"
import type { RankingMode } from "./TraceRankingExplanation"
import { TraceInspectionWorkspace } from "./TraceInspectionWorkspace"

export interface TraceDetailDialogProps {
  trace: TraceDetail | null
  isOpen: boolean
  /** `missing` is the project's 404: the trace is not in this project. */
  status: "loading" | "ready" | "error" | "missing"
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
  if (trace.output === null && attempt.results.length === 0) return null
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

/** "Search · Nov 7, 11:35 AM": what ran and when, the one line under the title. */
function subtitleOf(trace: TraceDetail | null): string | undefined {
  if (trace === null) return undefined
  const operation = trace.operation === "fetch" ? "Fetch" : trace.operation === "search" ? "Search" : null
  const parsed = new Date(trace.startedAt)
  const time = Number.isNaN(parsed.getTime()) ? null : formatDateTime(trace.startedAt)
  const parts = [operation, time].filter((part): part is string => part !== null)
  return parts.length === 0 ? undefined : parts.join(" · ")
}

/** The recorded query or URL; a metadata-only trace says so with one quiet tag. */
function inputValue(trace: TraceDetail) {
  if (trace.input === null) {
    const noun = trace.operation === "fetch" ? "URL" : "Query"
    return (
      <span className="inline-flex items-center gap-2">
        <span className="text-[12px] text-[var(--muted)]">{noun} not stored</span>
        <Tag title="Only timing was stored for this trace">Metadata only</Tag>
      </span>
    )
  }
  return (
    <p
      title={trace.input}
      className="m-0 mono max-h-12 overflow-y-auto text-[12px] leading-[18px] text-[var(--text)] whitespace-pre-wrap [overflow-wrap:anywhere]"
    >
      {trace.input}
    </p>
  )
}

interface ReadyViewOptions {
  trace: TraceDetail
  attempt: TraceProviderAttempt | null
  providerSpanId: string | null
}

/**
 * The decoded detail, top to bottom: what was asked beside the summary rail
 * (status, provider, time, results), any failure, then one workspace that
 * switches between the recorded results and the stage timeline.
 */
function readyView({ trace, attempt, providerSpanId }: ReadyViewOptions) {
  // Only a fused fanout is ranking across providers; a single-provider trace
  // (or one provider picked out of a fanout) shows that provider's own order.
  const mode: RankingMode =
    attempt !== null || trace.provider !== "aggregated" ? "provider" : "fusion"
  return (
    <div className="flex min-w-0 flex-col gap-3 text-[13px]">
      <div className="grid min-w-0 gap-2 sm:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] sm:items-stretch">
        <TraceDetailSection title={trace.operation === "fetch" ? "URL" : "Query"}>
          {inputValue(trace)}
        </TraceDetailSection>
        <TraceDetailSummary trace={trace} attempt={attempt} />
      </div>
      <TraceDetailError trace={trace} />
      <TraceInspectionWorkspace
        key={`${trace.traceId}:${providerSpanId ?? "all"}`}
        trace={trace}
        output={scopedOutput(trace, providerSpanId)}
        attempt={attempt}
        mode={mode}
      />
    </div>
  )
}

/**
 * Trace detail. The dialog sizes to its content: a short trace stays short,
 * and a long result list or timeline scrolls inside its own pane. Scoped to a
 * provider attempt, the results show that attempt's response instead.
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
      subtitle={status === "ready" ? subtitleOf(trace) : undefined}
      maxWidth="7xl"
    >
      {status === "loading" && (
        <p className="text-[13px] text-[var(--muted)]" role="status">
          Loading trace detail...
        </p>
      )}

      {status === "error" && (
        <div className="space-y-3">
          <p role="alert" className="text-[13px]" style={{ color: "var(--status-danger)" }}>
            Trace detail unavailable: {error?.replace(/\.$/, "")}
          </p>
          <Button variant="outline" size="form" onClick={onRetry}>
            Retry
          </Button>
        </div>
      )}

      {status === "missing" && (
        <p role="alert" className="text-[13px] text-[var(--muted)]">
          {error?.replace(/\.$/, "")}
        </p>
      )}

      {status === "ready" && trace !== null && readyView({ trace, attempt, providerSpanId })}
    </Modal>
  )
}
