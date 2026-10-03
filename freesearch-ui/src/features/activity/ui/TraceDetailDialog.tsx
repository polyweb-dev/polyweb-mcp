import { Modal } from "@/shared/ui/Modal"
import type { TraceDetail } from "@/domains/activity"
import { TraceDetailError } from "./TraceDetailError"
import { TraceDetailSection } from "./TraceDetailSection"
import { TraceDetailSummary } from "./TraceDetailSummary"
import { TraceDisclosure } from "./TraceDisclosure"
import { TraceResults } from "./TraceResults"
import { TraceTechnicalDetails } from "./TraceTechnicalDetails"
import { TraceTimeline } from "./TraceTimeline"

export interface TraceDetailDialogProps {
  trace: TraceDetail | null
  isOpen: boolean
  status: "loading" | "ready" | "error"
  error: string | null
  onClose: () => void
  onRetry: () => void
}

/**
 * Trace detail: summary first, then input, results, stage timeline, and the
 * collapsed technical projection. Content is labelled as locally stored data.
 */
export function TraceDetailDialog({
  trace,
  isOpen,
  status,
  error,
  onClose,
  onRetry,
}: TraceDetailDialogProps) {
  if (!isOpen) return null
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Trace detail"
      subtitle="Stored locally in this FreeSearch database; the query and its results are shown only here."
      maxWidth="4xl"
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
          <button
            type="button"
            onClick={onRetry}
            className="rounded border border-[var(--border-subtle)] px-3 py-1 text-[13px] text-[var(--text-strong)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)]/40"
          >
            Retry
          </button>
        </div>
      )}

      {status === "ready" && trace !== null && (
        <div className="space-y-5 text-[13px]">
          <TraceDetailSummary trace={trace} />
          <TraceDetailError trace={trace} />

          <TraceDetailSection
            title={trace.operation === "fetch" ? "URL fetched" : "Query sent"}
          >
            <p className="mono break-all rounded border border-[var(--border-subtle)] bg-[var(--elevated)] p-3 text-[var(--text)]">
              {trace.input ?? "—"}
            </p>
          </TraceDetailSection>

          <TraceDetailSection title="Results returned">
            <TraceResults output={trace.output} />
          </TraceDetailSection>

          <TraceDisclosure title="Stage timeline" defaultOpen>
            <TraceTimeline stages={trace.stages} totalMs={trace.totalMs} />
          </TraceDisclosure>

          <TraceDisclosure title="Technical details">
            <TraceTechnicalDetails trace={trace} />
          </TraceDisclosure>
        </div>
      )}
    </Modal>
  )
}
