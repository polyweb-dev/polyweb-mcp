import { cn } from "cn"
import type { TraceOutcome } from "@/domains/activity"

const LABELS: Record<TraceOutcome, string> = {
  success: "Success",
  partial: "Partial",
  error: "Error",
}

function outcomeColor(outcome: TraceOutcome): string {
  if (outcome === "success") return "var(--status-healthy)"
  if (outcome === "partial") return "var(--status-warning)"
  return "var(--status-danger)"
}

/** Outcome label shared by the Activity list, dialog summary, and timeline. */
export function TraceStatusPill({
  outcome,
  className,
}: {
  outcome: TraceOutcome
  className?: string
}) {
  return (
    <span
      className={cn("whitespace-nowrap text-[12px] font-medium", className)}
      style={{ color: outcomeColor(outcome) }}
    >
      {LABELS[outcome]}
    </span>
  )
}
