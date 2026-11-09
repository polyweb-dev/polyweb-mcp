import { useEffect, useState } from "react"
import { formatDateTime, formatLatency, formatRelativeTime } from "@/shared/lib/formatTime"
import { StatusDot, type StatusTone } from "./StatusDot"

type HealthState = "healthy" | "degraded" | "rate_limited" | "circuit_broken" | "offline"
const HEALTH: Record<HealthState | "failing" | "testing", { label: string; tone: StatusTone }> = {
  healthy: { label: "Healthy", tone: "positive" },
  degraded: { label: "Degraded", tone: "warning" },
  rate_limited: { label: "Rate limited", tone: "warning" },
  circuit_broken: { label: "Temporarily paused", tone: "negative" },
  offline: { label: "Unavailable", tone: "negative" },
  failing: { label: "Failing", tone: "negative" },
  testing: { label: "Testing", tone: "neutral" },
}

interface TestResult {
  success: boolean
  checkedAt: number
  latencyMs: number
  message: string
}

function observedStatus(health: HealthState | null, checkedAt: string | null | undefined, result?: TestResult) {
  const callAt = checkedAt == null ? NaN : Date.parse(checkedAt)
  if (result && Number.isFinite(result.checkedAt) && (!Number.isFinite(callAt) || result.checkedAt > callAt)) {
    const detail = result.success ? formatLatency(result.latencyMs) : result.message
    return {
      status: HEALTH[result.success ? "healthy" : "failing"], at: result.checkedAt,
      title: `Last test: ${formatDateTime(new Date(result.checkedAt).toISOString())} · ${detail}`,
    }
  }
  return {
    status: health === null || checkedAt === null ? undefined : HEALTH[health], at: callAt,
    title: Number.isFinite(callAt) && checkedAt ? `Last call: ${formatDateTime(checkedAt)}` : undefined,
  }
}

/** One health label and observation time across tables and dialogs. */
export function HealthStatus({ health, checkedAt, result, testing = false, now }: {
  health: HealthState | null
  checkedAt?: string | null
  result?: TestResult
  testing?: boolean
  now?: number
}) {
  const [clock, setClock] = useState(() => Date.now())
  useEffect(() => {
    if (now !== undefined) return
    const timer = window.setInterval(() => setClock(Date.now()), 60_000)
    return () => window.clearInterval(timer)
  }, [now])
  const observation = observedStatus(health, checkedAt, result)
  const status = testing ? HEALTH.testing : observation.status
  if (!status) return <span className="text-[var(--muted)]" title="No result yet">
    <span aria-hidden="true">—</span><span className="sr-only">Health not known</span>
  </span>
  const age = !testing && Number.isFinite(observation.at) ? ` · ${formatRelativeTime(observation.at, now ?? clock)}` : ""
  return <span title={testing ? undefined : observation.title}>
    <StatusDot tone={status.tone} label={`${status.label}${age}`} />
  </span>
}
