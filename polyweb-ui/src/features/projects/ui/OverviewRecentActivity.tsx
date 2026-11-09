import { useCallback, useState } from "react"
import { listProjectTraces } from "@/domains/activity"
import type { TraceOutcome, TraceSummary } from "@/domains/activity"
import { providerIdentity } from "@/domains/providers"
import { formatDateTime, formatLatency, formatRelativeTime } from "@/shared/lib/formatTime"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import { EmptyState } from "@/shared/ui/EmptyState"
import { ProviderBadge } from "@/shared/ui/ProviderBadge"
import { Section } from "@/shared/ui/Section"
import { StatusDot, type StatusTone } from "@/shared/ui/StatusDot"
import { SectionLink } from "./SectionLink"

const RECENT_LIMIT = 6

const OUTCOME: Record<TraceOutcome, { tone: StatusTone; label: string }> = {
  success: { tone: "positive", label: "Success" },
  partial: { tone: "warning", label: "Partial" },
  error: { tone: "negative", label: "Error" },
}

function providerCell(summary: TraceSummary) {
  const identity = summary.provider === null ? null : providerIdentity(summary.provider)
  if (identity === null || identity.id === "" || summary.provider === "aggregated") {
    return summary.providerLabel
  }
  return <ProviderBadge providerId={identity.id} name={identity.name} logoClassName="size-3.5" />
}

function operationLabel(summary: TraceSummary): string {
  if (summary.operation === "search") return "Search"
  if (summary.operation === "fetch") return "Fetch"
  return "Other"
}

/** The latest traces of the project, payload-free, with a way into Activity. */
export function OverviewRecentActivity({ accountId, projectId }: { accountId: string; projectId: string }) {
  const [now] = useState(Date.now)
  const load = useCallback(
    (signal: AbortSignal) => listProjectTraces(projectId, { limit: RECENT_LIMIT }, signal),
    [projectId]
  )
  const traces = useScopedResource({ scopeKey: `recent:${accountId}:${projectId}`, load })
  const activityPath = `/p/${projectId}/activity`

  return (
    <Section
      title="Recent activity"
      actions={<SectionLink to={activityPath}>View all activity</SectionLink>}
    >
      {traces.status === "loading" && (
        <p role="status" className="text-[13px] text-[var(--muted)]">
          Loading activity…
        </p>
      )}
      {traces.status === "error" && (
        <p className="text-[13px] text-[var(--muted)]">Recent activity is unavailable right now</p>
      )}
      {traces.status === "ready" && traces.data.items.length === 0 && (
        <EmptyState
          title="No searches or fetches yet"
          description="Calls from the Playground and from API keys show up here"
        />
      )}
      {traces.status === "ready" && traces.data.items.length > 0 && (
        <div className="fs-panel overflow-hidden">
          <table aria-label="Recent activity" className="fs-table">
            <thead>
              <tr>
                <th scope="col">Time</th>
                <th scope="col">Operation</th>
                <th scope="col">Provider</th>
                <th scope="col">Status</th>
                <th scope="col" className="text-right">Latency</th>
              </tr>
            </thead>
            <tbody>
              {traces.data.items.map((summary) => (
                <tr key={summary.traceId}>
                  <td className="tnum text-[var(--muted)]" title={formatDateTime(summary.startedAt)}>
                    {formatRelativeTime(Date.parse(summary.startedAt), now)}
                  </td>
                  <td>{operationLabel(summary)}</td>
                  <td className="fs-cell-strong">{providerCell(summary)}</td>
                  <td>
                    <StatusDot {...OUTCOME[summary.outcome]} />
                  </td>
                  <td className="tnum text-right">{formatLatency(summary.durationMs)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  )
}
