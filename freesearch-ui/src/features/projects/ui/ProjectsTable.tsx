import { ChevronRight } from "lucide-react"
import { Link } from "react-router"
import type { Project } from "@/domains/projects"
import { formatDate } from "@/shared/lib/formatTime"
import { Tag } from "@/shared/ui/Tag"

/**
 * The caller's projects, by name: the name links to the overview, the slug
 * sits in its own column, and only an archived project carries a tag.
 */
export function ProjectsTable({ projects, lastProjectId }: { projects: Project[]; lastProjectId: string | null }) {
  const sorted = [...projects].sort((a, b) => a.name.localeCompare(b.name))
  return (
    <div className="fs-panel overflow-hidden">
      <table aria-label="Projects" className="fs-table">
        <thead>
          <tr>
            <th scope="col">Name</th>
            <th scope="col">Slug</th>
            <th scope="col">Created</th>
            <th scope="col" className="fs-cell-actions">
              <span className="sr-only">Open</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((project) => (
            <tr key={project.id}>
              <td>
                <span className="flex min-w-0 items-center gap-2">
                  <Link
                    to={`/p/${project.id}`}
                    className="truncate font-medium text-[var(--text-strong)] hover:underline focus-visible:underline focus-visible:outline-none"
                  >
                    {project.name}
                  </Link>
                  {project.status === "archived" && <Tag>Archived</Tag>}
                  {project.id === lastProjectId && (
                    <span className="text-[12px] whitespace-nowrap text-[var(--muted)]">Last opened</span>
                  )}
                </span>
              </td>
              <td className="font-mono text-[12px] text-[var(--muted)]">{project.slug}</td>
              <td className="tnum text-[var(--muted)]">{formatDate(project.created_at)}</td>
              <td className="fs-cell-actions">
                <ChevronRight aria-hidden="true" className="ml-auto size-4 text-[var(--muted)]" />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
