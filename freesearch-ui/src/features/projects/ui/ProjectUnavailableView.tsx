import { Link } from "react-router"
import { PROJECT_UNAVAILABLE_MESSAGE } from "@/domains/projects"

/**
 * Neutral view for an inaccessible or unknown project.
 *
 * Unknown and inaccessible look identical on purpose: the view names neither.
 */
export function ProjectUnavailableView() {
  return (
    <section className="flex flex-1 flex-col space-y-4">
      <header className="border-b border-[var(--border-subtle)] pb-2">
        <h2 className="text-[var(--text-strong)]">Project unavailable</h2>
      </header>
      <p role="alert" className="text-[13px] text-[var(--muted)]">
        {PROJECT_UNAVAILABLE_MESSAGE}
      </p>
      <p className="text-[13px]">
        <Link to="/projects" className="text-[var(--signal)] hover:underline">
          All projects
        </Link>
      </p>
    </section>
  )
}
