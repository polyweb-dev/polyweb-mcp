import type { ReactNode } from "react"
import { Navigate, Route, Routes } from "react-router"
import { useProjectScope } from "@/domains/projects"
import { ActivityPage } from "@/features/activity/ui/ActivityPage"
import { ProjectPlaygroundPage } from "@/features/playground/ui/ProjectPlaygroundPage"
import { ProjectPlaygroundScope } from "@/features/playground/ui/ProjectPlaygroundScope"
import { ProjectUsagePage } from "@/features/usage/ui/ProjectUsagePage"
import { ProjectApiKeysPage } from "@/features/projects/ui/ProjectApiKeysPage"
import { ProjectScopeGate } from "@/features/projects/ui/ProjectScopeGate"
import { ProjectMembersPage } from "@/features/projects/ui/ProjectMembersPage"
import { ProjectOverviewPage } from "@/features/projects/ui/ProjectOverviewPage"
import { ProjectSectionGate } from "./ProjectSectionGate"
import { PROJECT_SECTIONS, projectPath, type ProjectSectionId } from "./routes"

/** Page of each registered project section. A new section adds its page here. */
const SECTION_PAGES: Record<ProjectSectionId, (accountId: string) => ReactNode> = {
  overview: () => <ProjectOverviewPage />,
  playground: (accountId) => <ProjectPlaygroundPage accountId={accountId} />,
  activity: () => <ActivityPage />,
  usage: () => <ProjectUsagePage />,
  members: (accountId) => <ProjectMembersPage accountId={accountId} />,
  apiKeys: (accountId) => <ProjectApiKeysPage accountId={accountId} />,
}

/**
 * Project-scoped subtree of the workspace.
 *
 * The shell's `ProjectScopeProvider` owns the access state of the URL
 * project, so the sidebar and the page share one descriptor. The project
 * playground scope (store and execution) wraps every section, so a section
 * switch keeps an in-flight playground request. The scope and the routes
 * mount with `key={accountId:projectId}`, so a project switch aborts that
 * request and remounts every page — forms, results, drafts and one-time keys
 * of the previous project can never bleed into the next. Each section comes
 * from the registry, behind the access gate and its own permission gate. Unknown sections redirect to the
 * overview, so no account-scoped data renders under a project URL.
 */
export function ProjectWorkspace({ accountId }: { accountId: string }) {
  const { projectId } = useProjectScope()
  const scopeKey = `${accountId}:${projectId}`

  return (
    <ProjectPlaygroundScope key={scopeKey} accountId={accountId} projectId={projectId}>
      <Routes key={scopeKey}>
        {PROJECT_SECTIONS.map(({ id, segment }) => {
          const element = (
            <ProjectScopeGate>
              <ProjectSectionGate section={id}>{SECTION_PAGES[id](accountId)}</ProjectSectionGate>
            </ProjectScopeGate>
          )
          return segment === "" ? (
            <Route key={id} index element={element} />
          ) : (
            <Route key={id} path={segment} element={element} />
          )
        })}
        <Route path="*" element={<Navigate to={projectPath(projectId)} replace />} />
      </Routes>
    </ProjectPlaygroundScope>
  )
}
