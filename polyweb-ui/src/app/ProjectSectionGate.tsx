import type { ReactNode } from "react"
import { Navigate } from "react-router"
import { useProjectScope } from "@/domains/projects"
import { ProjectUnavailableView } from "@/features/projects/ui/ProjectUnavailableView"
import { canAccessProjectSection, projectPath, type ProjectSectionId } from "./routes"

/**
 * Permission gate of one project section.
 *
 * It renders below `ProjectScopeGate`, so the access descriptor is ready. A
 * section whose permission is absent redirects to the project overview; an
 * overview without `project.read` shows the neutral unavailable view, so the
 * redirect can never loop.
 */
export function ProjectSectionGate({
  section,
  children,
}: {
  section: ProjectSectionId
  children: ReactNode
}) {
  const { projectId, accessState } = useProjectScope()
  const access = accessState.status === "ready" ? accessState.data : null
  if (canAccessProjectSection(section, access)) return <>{children}</>
  if (section === "overview") return <ProjectUnavailableView />
  return <Navigate to={projectPath(projectId)} replace />
}
