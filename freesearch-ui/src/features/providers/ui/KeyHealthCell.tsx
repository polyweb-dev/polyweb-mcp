import { useEffect, useState } from "react"
import { StatusDot, type StatusTone } from "@/shared/ui/StatusDot"
import { readableWord } from "../model/credentialDisplay"
import { formatDateTime, formatRelativeTime } from "@/shared/lib/formatTime"

function healthTone(health: string): StatusTone {
  if (health === "healthy") return "positive"
  if (health === "degraded" || health === "rate_limited") return "warning"
  return "negative"
}

/** Last known health of a key; a muted dash when nothing is known. */
export function KeyHealthCell({ health, checkedAt, project }: { health: string | null; checkedAt?: string | null; project?: boolean }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60_000)
    return () => window.clearInterval(timer)
  }, [])
  if (health === null || health === "unknown") {
    return (
      <span className="text-[var(--muted)]">
        <span aria-hidden="true">—</span>
        <span className="sr-only">Health not known</span>
      </span>
    )
  }
  const at = checkedAt == null ? NaN : Date.parse(checkedAt)
  const age = Number.isFinite(at) ? ` · ${formatRelativeTime(at, now)}` : ""
  return (
    <span title={checkedAt && Number.isFinite(at) ? formatDateTime(checkedAt) : undefined}>
      <StatusDot tone={project && health === "degraded" ? "negative" : healthTone(health)}
        label={`${project && health === "degraded" ? "Error" : readableWord(health)}${age}`} />
    </span>
  )
}
