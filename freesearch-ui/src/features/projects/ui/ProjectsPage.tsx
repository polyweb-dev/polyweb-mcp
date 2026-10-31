import { Link } from "react-router"
import { Button } from "@/shared/ui/button"
import { canCreateProjects, resolveLastProject, useProjects } from "@/domains/projects"
import { ProjectCreateForm } from "./ProjectCreateForm"

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
  const lastProject = projects.find((project) => project.id === lastProjectId) ?? null

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
        <Button type="button" variant="outline" onClick={() => void reloadProjects()}>
          Retry
        </Button>
      </div>
    )
  }

  return (
    <section className="flex flex-1 flex-col space-y-6">
      <header className="border-b border-[var(--border-subtle)] pb-2">
        <h2 className="text-[var(--text-strong)]">Projects</h2>
      </header>

      {lastProject !== null && (
        <p className="text-[13px]">
          <Link
            to={`/p/${lastProject.id}`}
            className="text-[var(--signal)] hover:underline"
          >
            Continue with {lastProject.name}
          </Link>
        </p>
      )}

      {projects.length === 0 ? (
        <div className="space-y-1 text-[13px] text-[var(--muted)]">
          <p>You are not a member of any project.</p>
          <p>Ask a system administrator to add you.</p>
        </div>
      ) : (
        <ul className="space-y-1">
          {projects.map((project) => (
            <li key={project.id}>
              <Link
                to={`/p/${project.id}`}
                className="flex items-center justify-between rounded px-2 py-1.5 text-[13px] text-[var(--text)] hover:bg-[var(--secondary)]"
              >
                <span className="min-w-0 truncate">{project.name}</span>
                {project.status === "archived" && (
                  <span className="text-[10px] uppercase tracking-wide text-[var(--muted)]">
                    Archived
                  </span>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}

      {canCreateProjects(systemAccess) && (
        <ProjectCreateForm defaultAdminEmail={defaultAdminEmail} />
      )}
    </section>
  )
}
