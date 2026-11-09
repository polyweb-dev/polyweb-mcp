import { Navigate } from "react-router"
import { resolveLastProject, useProjects } from "@/domains/projects"
import { PROJECTS_PATH, projectPath, type ProjectSectionId } from "./routes"
import { WorkspaceAccessGate } from "./WorkspaceAccessGate"

/**
 * Project-first landing of `/`, of every unknown path, and of the former
 * global section paths (`/playground`, `/activity`).
 *
 * Once the project list has loaded, it redirects to the given section (the
 * overview by default) of the validated last project, else to the project
 * list. The remembered project is honored only while it is still in the
 * readable list; the landing never writes the preference.
 */
export function WorkspaceLanding({ section = "overview" }: { section?: ProjectSectionId }) {
  const { accountId, projects } = useProjects()
  const lastProjectId = resolveLastProject(accountId, projects)
  const target = lastProjectId === null ? PROJECTS_PATH : projectPath(lastProjectId, section)
  return (
    <WorkspaceAccessGate>
      <Navigate to={target} replace />
    </WorkspaceAccessGate>
  )
}
