import { cn } from "cn"
import type { TraceOutcome } from "@/domains/activity"
import { StatusDot, type StatusTone } from "@/shared/ui/StatusDot"

const LABELS: Record<TraceOutcome, string> = {
  success: "Success",
  partial: "Partial",
  error: "Error",
}

const TONES: Record<TraceOutcome, StatusTone> = {
  success: "positive",
  partial: "warning",
  error: "negative",
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
    <span className={cn("text-[13px]", className)}>
      <StatusDot tone={TONES[outcome]} label={LABELS[outcome]} />
    </span>
  )
}
