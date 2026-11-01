import { useCallback } from "react"
import {
  getProjectDashboard,
  summarizeUsageByOperation,
  usageOperationLabel,
  usageUnitsText,
} from "@/domains/usage"
import { useScopedResource } from "@/shared/lib/useScopedResource"

/**
 * Compact usage summary of the project overview, from the project dashboard:
 * total events and units per operation. Keyed by `accountId:projectId`, so a
 * project switch aborts the read and drops its late result. It never shows
 * the shared provider quota or health.
 */
export function ProjectUsageSummary({
  accountId,
  projectId,
}: {
  accountId: string
  projectId: string
}) {
  const load = useCallback((signal: AbortSignal) => getProjectDashboard(projectId, signal), [projectId])
  const dashboard = useScopedResource({ scopeKey: `${accountId}:${projectId}`, load })
  const summaries =
    dashboard.status === "ready" ? summarizeUsageByOperation(dashboard.data.totals) : []

  return (
    <section aria-label="Usage summary" className="space-y-1">
      <h3 className="text-[13px] font-medium text-[var(--text-strong)]">Usage</h3>
      {dashboard.status === "loading" && (
        <p role="status" className="text-[13px] text-[var(--muted)]">
          Loading usage...
        </p>
      )}
      {dashboard.status === "error" && (
        <p className="text-[13px] text-[var(--muted)]">Usage is unavailable right now.</p>
      )}
      {dashboard.status === "ready" && summaries.length === 0 && (
        <p className="text-[13px] text-[var(--muted)]">No usage recorded for this project yet.</p>
      )}
      {summaries.length > 0 && (
        <dl className="grid max-w-xl grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-[13px]">
          {summaries.map((summary) => (
            <div key={summary.operation} className="contents">
              <dt className="text-[var(--muted)]">{usageOperationLabel(summary.operation)}</dt>
              <dd className="m-0 tnum text-[var(--text)]">
                {summary.eventCount} {summary.eventCount === 1 ? "event" : "events"}
                {summary.units.map((amount) => (
                  <span key={amount.unitKind ?? "legacy"}>
                    {" · "}
                    {usageUnitsText(amount.units, amount.unitKind)}
                  </span>
                ))}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  )
}
