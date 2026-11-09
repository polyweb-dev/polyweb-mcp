import { useCallback } from "react"
import { getProjectDashboard } from "@/domains/usage"
import type { ProjectOrder } from "@/domains/routing"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import { Stat } from "@/shared/ui/Stat"
import { formatCallCost, formatCostTotal } from "@/domains/providers"
import { usageFigures } from "../model/usageFigures"

/** The dashboard totals carry no time window: they count every recorded call. */
const PERIOD = "All time"

/**
 * Summary row of the project overview, from the project dashboard: all-time
 * searches, fetches and known provider cost in dollars.
 * Keyed by `accountId:projectId`, so a project switch aborts the
 * read and drops its late result. It never shows the shared provider quota
 * or health.
 */
export function ProjectUsageSummary({
  accountId,
  projectId,
  order,
}: {
  accountId: string
  projectId: string
  order?: ProjectOrder | undefined
}) {
  const load = useCallback((signal: AbortSignal) => getProjectDashboard(projectId, signal), [projectId])
  const dashboard = useScopedResource({ scopeKey: `${accountId}:${projectId}`, load })

  if (dashboard.status === "loading") {
    return (
      <section aria-label="Usage summary">
        <p role="status" className="text-[13px] text-[var(--muted)]">
          Loading usage…
        </p>
      </section>
    )
  }
  if (dashboard.status === "error") {
    return (
      <section aria-label="Usage summary">
        <p className="text-[13px] text-[var(--muted)]">Usage is unavailable right now</p>
      </section>
    )
  }

  const figures = usageFigures(dashboard.data.totals, order)
  return (
    <section aria-label="Usage summary">
      <dl className="grid grid-cols-3 gap-3">
        <Stat label="Searches" value={figures.searches.toLocaleString("en-US")} detail={PERIOD} />
        <Stat label="Fetches" value={figures.fetches.toLocaleString("en-US")} detail={PERIOD} />
        <Stat
          label={figures.costIncomplete ? "Known provider cost" : "Provider cost"}
          value={figures.free ? formatCallCost(0) : formatCostTotal(figures.usd)}
          detail={PERIOD}
        />
      </dl>
    </section>
  )
}
