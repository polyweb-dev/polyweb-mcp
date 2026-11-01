import { useProjectScope, useProjects } from "@/domains/projects"
import { errorMessage } from "@/shared/api/http"
import { Button } from "@/shared/ui/button"
import { useProjectUsage } from "../model/useProjectUsage"
import { RecentUsageTable } from "./RecentUsageTable"
import { UsageTotalsTable } from "./UsageTotalsTable"

/**
 * Usage page of the URL project: units and events per provider and
 * operation, plus the recent ledger. It shows this project's own usage only,
 * never the shared provider quota or health.
 */
export function ProjectUsagePage() {
  const { accountId } = useProjects()
  const { projectId } = useProjectScope()
  const usage = useProjectUsage(accountId, projectId)

  return (
    <section className="flex flex-1 flex-col space-y-6">
      <header className="border-b border-[var(--border-subtle)] pb-2">
        <h2 className="text-[var(--text-strong)]">Usage</h2>
        <p className="mt-0.5 text-[13px] text-[var(--muted)]">
          This project's usage only. Shared provider quota and health are not shown here.
        </p>
      </header>

      {usage.status === "loading" && (
        <p role="status" className="text-[13px] text-[var(--muted)]">
          Loading usage...
        </p>
      )}

      {usage.status === "error" && (
        <div className="space-y-3">
          <p role="alert" className="text-[13px]" style={{ color: "var(--status-danger)" }}>
            Usage unavailable — {errorMessage(usage.error, "Usage unavailable")}
          </p>
          <Button variant="outline" size="sm" onClick={() => void usage.reload()}>
            Retry
          </Button>
        </div>
      )}

      {usage.status === "ready" && (
        <>
          <div className="space-y-2">
            <h3 className="text-[13px] font-medium text-[var(--text-strong)]">Totals</h3>
            <UsageTotalsTable totals={usage.data.totals} />
          </div>
          <div className="space-y-2">
            <h3 className="text-[13px] font-medium text-[var(--text-strong)]">Recent usage</h3>
            <RecentUsageTable entries={usage.data.recent} />
          </div>
        </>
      )}
    </section>
  )
}
