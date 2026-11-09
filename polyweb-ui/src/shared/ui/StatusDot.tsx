import { cn } from "cn"

export type StatusTone = "positive" | "warning" | "negative" | "neutral"

const DOT_CLASS: Record<StatusTone, string> = {
  positive: "bg-[var(--status-healthy)]",
  warning: "bg-[var(--status-warning)]",
  negative: "bg-[var(--status-danger)]",
  neutral: "bg-[var(--muted)]",
}

/** One status as a small colored dot and plain text. The text carries the meaning. */
export function StatusDot({ tone, label }: { tone: StatusTone; label: string }) {
  return (
    <span className="inline-flex items-center gap-2 whitespace-nowrap">
      <span aria-hidden="true" className={cn("size-1.5 shrink-0 rounded-full", DOT_CLASS[tone])} />
      <span>{label}</span>
    </span>
  )
}
