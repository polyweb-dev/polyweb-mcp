import { Navigate } from "react-router"
import { resolveLastProject, useProjects } from "@/domains/projects"
import { PROJECTS_PATH, projectPath } from "./routes"
import { WorkspaceAccessGate } from "./WorkspaceAccessGate"

/**
 * Project-first landing of `/` and of every unknown path.
 *
 * Once the project list has loaded, it redirects to the validated last
 * project's overview, else to the project list. The remembered project is
 * honored only while it is still in the readable list; the landing never
 * writes the preference.
 */
export function WorkspaceLanding() {
  const { accountId, projects } = useProjects()
  const lastProjectId = resolveLastProject(accountId, projects)
  const target = lastProjectId === null ? PROJECTS_PATH : projectPath(lastProjectId)
  return (
    <WorkspaceAccessGate>
      <Navigate to={target} replace />
    </WorkspaceAccessGate>
  )
}
