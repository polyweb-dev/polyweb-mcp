import { Navigate, Route, Routes, useParams } from "react-router"
import { useAuth } from "@/domains/auth"
import { ProjectScopeProvider, useProjects } from "@/domains/projects"
import { ProjectScopeGate } from "@/features/projects/ui/ProjectScopeGate"
import { ProjectMembersPage } from "@/features/projects/ui/ProjectMembersPage"
import { ProjectOverviewPage } from "@/features/projects/ui/ProjectOverviewPage"
import { PROJECTS_PATH, TAB_PATHS, projectPath } from "./routes"

/**
 * Project-scoped subtree of the workspace.
 *
 * The provider mounts with `key={accountId:projectId}`, so a project switch
 * remounts the entire subtree — forms, results, and drafts of the previous
 * project can never bleed into the next. The catch-all redirect keeps every
 * account-scoped surface (`/p/x/usage`, `/p/x/activity`, …) on the overview,
 * so no account-scoped data renders under a project URL.
 */
export function ProjectWorkspace() {
  const { account } = useAuth()
  const { availability } = useProjects()
  const { projectId } = useParams()

  if (account === null || projectId === undefined) {
    return <Navigate to={PROJECTS_PATH} replace />
  }
  if (availability === "unavailable") {
    return <Navigate to={TAB_PATHS.playground} replace />
  }

  const scopeKey = `${account.id}:${projectId}`
  return (
    <ProjectScopeProvider
      key={scopeKey}
      accountId={account.id}
      projectId={projectId}
    >
      <Routes>
        <Route
          index
          element={
            <ProjectScopeGate>
              <ProjectOverviewPage />
            </ProjectScopeGate>
          }
        />
        <Route
          path="members"
          element={
            <ProjectScopeGate>
              <ProjectMembersPage accountId={account.id} />
            </ProjectScopeGate>
          }
        />
        <Route path="*" element={<Navigate to={projectPath(projectId)} replace />} />
      </Routes>
    </ProjectScopeProvider>
  )
}
