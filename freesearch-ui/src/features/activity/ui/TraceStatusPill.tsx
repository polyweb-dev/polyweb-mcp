import { cn } from "cn"
import type { TraceOutcome } from "@/domains/activity"

const LABELS: Record<TraceOutcome, string> = {
  success: "success",
  partial: "partial",
  error: "error",
}

function outcomeColor(outcome: TraceOutcome): string {
  if (outcome === "success") return "var(--status-healthy)"
  if (outcome === "partial") return "var(--status-warning)"
  return "var(--status-danger)"
}

/** Outcome pill shared by the Activity list, dialog summary, and timeline. */
export function TraceStatusPill({
  outcome,
  className,
}: {
  outcome: TraceOutcome
  className?: string
}) {
  return (
    <span
      className={cn("rounded px-1.5 py-0.5 text-[12px] font-medium", className)}
      style={{
        color: outcomeColor(outcome),
        background: "var(--elevated)",
        border: "1px solid var(--border-subtle)",
      }}
    >
      {LABELS[outcome]}
    </span>
  )
}
