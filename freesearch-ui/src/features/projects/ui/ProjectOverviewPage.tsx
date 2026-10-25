import { Link } from "react-router"
import { PROJECT_ROLE_LABELS, useProjectScope } from "@/domains/projects"
import type { ProjectRoleKey } from "@/domains/projects"

const PREVIEW_NOTICE =
  "Project playground, usage and activity are not available in this preview. " +
  "The account workspace keeps working as before."

function roleLabel(role: string): string {
  return PROJECT_ROLE_LABELS[role as ProjectRoleKey] ?? role
}

/**
 * Landing page of one project.
 *
 * The page shows the project status and the caller's role labels only. No
 * execution, usage, or activity data appears here; account-scoped surfaces
 * keep their existing routes.
 */
export function ProjectOverviewPage() {
  const { project, projectId, accessState } = useProjectScope()
  const roles = accessState.status === "ready" ? accessState.data.roles : []

  return (
    <section className="flex flex-1 flex-col space-y-6">
      <header className="border-b border-[var(--border-subtle)] pb-2">
        <h2 className="text-[var(--text-strong)]">{project?.name ?? "Project"}</h2>
        {project !== null && (
          <p className="mt-0.5 text-[13px] text-[var(--muted)]">
            Status: {project.status === "archived" ? "Archived" : "Active"}
          </p>
        )}
      </header>

      <div className="space-y-1">
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

      <p className="text-[13px]">
        <Link
          to={`/p/${projectId}/members`}
          className="text-[var(--signal)] hover:underline"
        >
          Members
        </Link>
      </p>

      <p role="note" className="max-w-xl text-[13px] text-[var(--muted)]">
        {PREVIEW_NOTICE}
      </p>
    </section>
  )
}
