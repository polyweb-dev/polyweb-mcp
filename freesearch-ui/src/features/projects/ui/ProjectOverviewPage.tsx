import { useCallback } from "react"
import {
  PROJECT_PERMISSIONS,
  PROJECT_ROLE_LABELS,
  hasPermission,
  useProjectScope,
  useProjects,
} from "@/domains/projects"
import type { ProjectRoleKey } from "@/domains/projects"
import { getProjectProviders } from "@/domains/providers"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import { PageHeader } from "@/shared/ui/PageHeader"
import { ProjectSetupChecklist } from "./ProjectSetupChecklist"
import { ProjectUsageSummary } from "./ProjectUsageSummary"

function roleLabel(role: string): string {
  return PROJECT_ROLE_LABELS[role as ProjectRoleKey] ?? role
}

/** Provider view of the overview page; loads only with providers.read. */
function useSetupView(accountId: string, projectId: string, enabled: boolean) {
  const load = useCallback(
    (signal: AbortSignal) => getProjectProviders(projectId, signal),
    [projectId]
  )
  const view = useScopedResource({
    scopeKey: `overview:${accountId}:${projectId}`,
    load,
    enabled,
  })
  const providers = view.status === "ready" ? view.data : []
  const hasCredential = providers.some((provider) => provider.available)
  const hasEffective = providers.some((provider) => provider.effectiveOperations.length > 0)
  return { showSetup: enabled && view.status === "ready" && !hasEffective, hasCredential, hasEffective }
}

/**
 * Landing page of one project.
 *
 * The page shows the project status, the caller's role labels and, with
 * `usage.read`, a compact summary of this project's own usage.
 */
export function ProjectOverviewPage() {
  const { accountId } = useProjects()
  const { project, projectId, accessState } = useProjectScope()
  const access = accessState.status === "ready" ? accessState.data : null
  const roles = access?.roles ?? []

  const canReadProviders = hasPermission(access, PROJECT_PERMISSIONS.providersRead)
  const canConfigureProviders = hasPermission(access, PROJECT_PERMISSIONS.providersConfigure)
  const { showSetup, hasCredential, hasEffective } = useSetupView(
    accountId,
    projectId,
    canReadProviders
  )

  return (
    <section className="flex flex-1 flex-col space-y-6">
      <PageHeader
        title={project?.name ?? "Project"}
        description={project === null ? undefined : project.status === "archived" ? "Archived project" : "Active project"}
      />

      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 className="text-[13px] font-medium text-[var(--text-strong)]">Your roles</h3>
        {roles.length === 0 ? (
          <p className="text-[13px] text-[var(--muted)]">No project roles.</p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            {roles.map((role) => (
              <li
                key={role}
                className="rounded border border-[var(--border-subtle)] px-2 py-0.5 text-[12px] text-[var(--text)]"
              >
                {roleLabel(role)}
              </li>
            ))}
          </ul>
        )}
      </div>

      {showSetup && (
        <ProjectSetupChecklist
          projectId={projectId}
          canConfigure={canConfigureProviders}
          hasCredential={hasCredential}
          hasEffective={hasEffective}
        />
      )}

      {hasPermission(access, PROJECT_PERMISSIONS.usageRead) && (
        <ProjectUsageSummary accountId={accountId} projectId={projectId} />
      )}
    </section>
  )
}
