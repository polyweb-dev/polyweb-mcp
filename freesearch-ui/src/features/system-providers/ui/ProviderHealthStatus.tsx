import type { ProviderHealthStatus as Health } from "@/domains/providers"
import { StatusDot, type StatusTone } from "@/shared/ui/StatusDot"
import { formatDateTime, formatLatency, formatRelativeTime } from "@/shared/lib/formatTime"
import type { TimedTestResult } from "./providerDisplay"

interface ProviderHealthStatusProps {
  result: TimedTestResult | undefined
  testing: boolean
  now: number
  health: Health
  checkedAt: string | null
}

const HEALTH: Record<Health, { label: string; tone: StatusTone }> = {
  healthy: { label: "Healthy", tone: "positive" },
  degraded: { label: "Degraded", tone: "warning" },
  rate_limited: { label: "Rate limited", tone: "warning" },
  circuit_broken: { label: "Temporarily paused", tone: "negative" },
  offline: { label: "Unavailable", tone: "negative" },
}

/** Latest known call or newer session test, with its exact time on hover. */
export function ProviderHealthStatus({ result, testing, now, health, checkedAt }: ProviderHealthStatusProps) {
  if (testing) return <StatusDot tone="neutral" label="Testing" />
  const callAt = checkedAt === null ? NaN : Date.parse(checkedAt)
  if (result !== undefined && (!Number.isFinite(callAt) || result.checkedAt > callAt)) {
    const time = formatDateTime(new Date(result.checkedAt).toISOString())
    const detail = result.success ? formatLatency(result.latencyMs) : result.message
    return (
      <span title={`Last test: ${time} · ${detail}`}>
        <StatusDot tone={result.success ? "positive" : "negative"} label={`${result.success ? "Healthy" : "Failing"} · ${formatRelativeTime(result.checkedAt, now)}`} />
      </span>
    )
  }
  if (!Number.isFinite(callAt) || checkedAt === null) {
    return <span className="text-[var(--muted)]" title="No result yet">—</span>
  }
  const status = HEALTH[health]
  return (
    <span title={`Last call: ${formatDateTime(checkedAt)}`}>
      <StatusDot tone={status.tone} label={`${status.label} · ${formatRelativeTime(callAt, now)}`} />
    </span>
  )
}
