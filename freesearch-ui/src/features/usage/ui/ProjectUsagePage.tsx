import { useCallback } from "react"
import { Link } from "react-router"
import { hasPermission, PROJECT_PERMISSIONS, useProjectScope, useProjects } from "@/domains/projects"
import { getProjectOrder } from "@/domains/routing"
import { errorMessage } from "@/shared/api/http"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import { Button, buttonVariants } from "@/shared/ui/button"
import { PageHeader } from "@/shared/ui/PageHeader"
import { Section } from "@/shared/ui/Section"
import { useProjectUsage } from "../model/useProjectUsage"
import { UsageTotalsTable } from "./UsageTotalsTable"

/**
 * Usage page of the URL project: calls and metered units per provider and
 * operation since the ledger began. Individual calls live in Activity, so
 * the page links there instead of repeating a second call ledger.
 */
export function ProjectUsagePage() {
  const { accountId } = useProjects()
  const { projectId, accessState } = useProjectScope()
  const usage = useProjectUsage(accountId, projectId)
  const canReadProviders = hasPermission(accessState.status === "ready" ? accessState.data : null, PROJECT_PERMISSIONS.providersRead)
  const loadOrder = useCallback((signal: AbortSignal) => getProjectOrder(projectId, signal), [projectId])
  const order = useScopedResource({ scopeKey: `usage:${accountId}:${projectId}`, load: loadOrder, enabled: canReadProviders })

  return (
    <section className="flex flex-1 flex-col space-y-6">
      <PageHeader
        title="Usage"
        description="What this project's calls used, per provider"
        actions={
          <Link
            to={`/p/${projectId}/activity`}
            className={buttonVariants({ variant: "outline", size: "form" })}
          >
            See every call in Activity
          </Link>
        }
      />

      {usage.status === "loading" && (
        <p role="status" className="text-[13px] text-[var(--muted)]">
          Loading usage…
        </p>
      )}

      {usage.status === "error" && (
        <div className="space-y-3">
          <p role="alert" className="text-[13px]" style={{ color: "var(--status-danger)" }}>
            Usage is unavailable: {errorMessage(usage.error, "Usage unavailable")}
          </p>
          <Button variant="outline" size="form" onClick={() => void usage.reload()}>
            Retry
          </Button>
        </div>
      )}

      {usage.status === "ready" && (
        <Section title="Totals by provider" description="All time">
          <UsageTotalsTable totals={usage.data.totals} order={order.status === "ready" ? order.data : undefined} />
        </Section>
      )}
    </section>
  )
}
