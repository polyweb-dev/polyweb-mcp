import { useEffect } from "react"
import { Button } from "@/shared/ui/button"
import { EmptyState } from "@/shared/ui/EmptyState"
import { PageHeader } from "@/shared/ui/PageHeader"
import { canCreateProjects, resolveLastProject, useProjects } from "@/domains/projects"
import { ProjectCreateForm } from "./ProjectCreateForm"
import { ProjectsTable } from "./ProjectsTable"

/**
 * Projects overview of the workspace.
 *
 * The list shows every project the caller can read. The create form appears
 * only when the live system access grants `project.create`, the permission the
 * backend enforces; it is never inferred from an account role. The shell
 * mounts it behind the workspace access gate; rendered on its own, a failed
 * load still shows an error with Retry instead of hiding the page.
 */
export function ProjectsPage({ defaultAdminEmail }: { defaultAdminEmail: string }) {
  const { accountId, availability, systemAccess, projects, reloadProjects } = useProjects()
  const lastProjectId = resolveLastProject(accountId, projects)

  // Refresh the list on entry so membership changes made elsewhere appear.
  useEffect(() => {
    void reloadProjects()
  }, [reloadProjects])

  if (availability === "loading") {
    return (
      <p role="status" className="text-[13px] text-[var(--muted)]">
        Loading projects…
      </p>
    )
  }
  if (availability === "unavailable") {
    return (
      <div role="alert" className="space-y-3 text-[13px] text-[var(--status-danger)]">
        <p>The project list could not be loaded.</p>
        <Button type="button" size="form" variant="outline" onClick={() => void reloadProjects()}>
          Retry
        </Button>
      </div>
    )
  }

  const canCreate = canCreateProjects(systemAccess)
  return (
    <section className="flex flex-1 flex-col">
      <PageHeader
        title="Projects"
        description="Each project has its own providers, members and API keys"
      />

      <div className={canCreate ? "grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_360px]" : undefined}>
        {projects.length === 0 ? (
          <EmptyState
            title="You are not a member of any project"
            description="Ask a system administrator to add you"
          />
        ) : (
          <ProjectsTable projects={projects} lastProjectId={lastProjectId} />
        )}
        {canCreate && <ProjectCreateForm defaultAdminEmail={defaultAdminEmail} />}
      </div>
    </section>
  )
}
