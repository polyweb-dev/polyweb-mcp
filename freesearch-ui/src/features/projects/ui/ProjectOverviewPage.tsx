import { useCallback } from "react"
import { PROJECT_PERMISSIONS, hasPermission, useProjectScope, useProjects } from "@/domains/projects"
import { getProjectProviderView, hasEffectiveRoute } from "@/domains/providers"
import { getProjectOrder } from "@/domains/routing"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import { OverviewRecentActivity } from "./OverviewRecentActivity"
import { OverviewRouteOrder } from "./OverviewRouteOrder"
import { ProjectOverviewHeader } from "./ProjectOverviewHeader"
import { ProjectSetupChecklist } from "./ProjectSetupChecklist"
import { ProjectUsageSummary } from "./ProjectUsageSummary"

const TWO_COLUMNS = "grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_360px]"
const ONE_COLUMN = "grid items-start gap-6"

/** Provider view of the overview page; loads only with providers.read. */
function useProviderView(accountId: string, projectId: string, enabled: boolean) {
  const load = useCallback(
    (signal: AbortSignal) => getProjectProviderView(projectId, signal),
    [projectId]
  )
  const view = useScopedResource({ scopeKey: `overview:${accountId}:${projectId}`, load, enabled })
  const providers = view.status === "ready" ? view.data.providers : []
  return {
    ready: enabled && view.status === "ready",
    hasCredential: providers.some((provider) => provider.credentials.length > 0),
    hasEffective: hasEffectiveRoute(providers),
  }
}

/**
 * Landing page of one project: its status and the caller's roles, the
 * setup guide while nothing can run, this project's search and fetch
 * figures, its latest traces and its route order. Each block loads only
 * with the permission that reads it.
 */
export function ProjectOverviewPage() {
  const { accountId } = useProjects()
  const { project, projectId, accessState } = useProjectScope()
  const access = accessState.status === "ready" ? accessState.data : null

  const canConfigureProviders = hasPermission(access, PROJECT_PERMISSIONS.providersConfigure)
  const canReadTraces = hasPermission(access, PROJECT_PERMISSIONS.tracesRead)
  const canReadProviders = hasPermission(access, PROJECT_PERMISSIONS.providersRead)
  const loadOrder = useCallback((signal: AbortSignal) => getProjectOrder(projectId, signal), [projectId])
  const order = useScopedResource({ scopeKey: `overview-order:${accountId}:${projectId}`, load: loadOrder, enabled: canReadProviders })
  const providerView = useProviderView(
    accountId,
    projectId,
    canReadProviders
  )

  return (
    <section className="flex flex-1 flex-col space-y-6">
      <ProjectOverviewHeader project={project} projectId={projectId} access={access} />

      {providerView.ready && !providerView.hasEffective && (
        <ProjectSetupChecklist
          projectId={projectId}
          canConfigure={canConfigureProviders}
          hasCredential={providerView.hasCredential}
          hasEffective={providerView.hasEffective}
        />
      )}

      {hasPermission(access, PROJECT_PERMISSIONS.usageRead) && (
        <ProjectUsageSummary accountId={accountId} projectId={projectId} order={order.status === "ready" ? order.data : undefined} />
      )}

      <div className={canReadTraces && canReadProviders ? TWO_COLUMNS : ONE_COLUMN}>
        {canReadTraces && <OverviewRecentActivity accountId={accountId} projectId={projectId} />}
        {canReadProviders && (
          <OverviewRouteOrder
            projectId={projectId}
            order={order}
            canConfigure={canConfigureProviders}
          />
        )}
      </div>
    </section>
  )
}
