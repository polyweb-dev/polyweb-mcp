import { useMemo } from "react"
import type { ReactNode } from "react"
import { Navigate, Route, Routes, useLocation } from "react-router"
import { Sidebar } from "@/app/layout/Sidebar"
import { ProjectWorkspace } from "./ProjectWorkspace"
import { ProjectsPage } from "@/features/projects/ui/ProjectsPage"
import { PlaygroundPage } from "@/features/playground/ui/PlaygroundPage"
import { RoutingEngine } from "@/components/routing/RoutingEngine"
import { QuotaAnalytics } from "@/components/quota/QuotaAnalytics"
import { ActivityPage } from "@/features/activity/ui/ActivityPage"
import { SettingsView } from "@/components/settings/SettingsView"
import { AccountPage } from "@/features/auth/ui/AccountPage"
import { AdminUsersPage } from "@/features/users/ui/AdminUsersPage"
import { ToastContainer } from "@/components/common/ToastContainer"
import { useAuth } from "@/domains/auth"
import { ProjectScopeProvider } from "@/domains/projects"
import { projectIdFromPath, workspaceRoutes, type TabId } from "./routes"
import { WorkspaceAccessGate } from "./WorkspaceAccessGate"
import { WorkspaceLanding } from "./WorkspaceLanding"
import { WorkspaceRouteGate } from "./WorkspaceRouteGate"

function routeElements(adminEmail: string): Record<TabId, ReactNode> {
  return {
    playground: <PlaygroundPage />,
    routing: <RoutingEngine />,
    quotas: <QuotaAnalytics />,
    activity: <ActivityPage />,
    settings: <SettingsView />,
    projects: (
      <WorkspaceAccessGate>
        <ProjectsPage defaultAdminEmail={adminEmail} />
      </WorkspaceAccessGate>
    ),
    account: <AccountPage />,
    adminUsers: <AdminUsersPage />,
  }
}

/**
 * Route gate and project scope of the workspace.
 *
 * Every gate reads effective permissions: global routes the system access
 * descriptor, project sections the project access descriptor. The project
 * scope sits above the sidebar and the page, keyed by `accountId:projectId`
 * from the URL, so both read one access state. `/` and unknown paths land on
 * the last valid project, else the project list. The legacy `/providers`
 * redirect stays verbatim.
 */
export function DashboardShell() {
  const { account } = useAuth()
  const { pathname } = useLocation()
  const accountId = account?.id ?? ""
  const adminEmail = account?.email ?? ""
  const elements = useMemo(() => routeElements(adminEmail), [adminEmail])

  return (
    <div
      className="flex min-h-screen flex-row font-sans"
      style={{ background: "var(--surface)", color: "var(--text)" }}
    >
      <ProjectScopeProvider accountId={accountId} projectId={projectIdFromPath(pathname)}>
        <Sidebar />

        <div className="flex min-w-0 flex-1 flex-col">
          <main className="min-w-0 flex-1 px-6 py-8 pt-16 sm:px-8 md:pt-8 lg:px-12 flex flex-col">
            <Routes>
              <Route path="/" element={<WorkspaceLanding />} />
              <Route path="/providers" element={<Navigate to="/settings" replace />} />
              <Route
                path="/p/:projectId/*"
                element={
                  <WorkspaceAccessGate>
                    <ProjectWorkspace accountId={accountId} />
                  </WorkspaceAccessGate>
                }
              />
              {workspaceRoutes.map(({ id, path }) => (
                <Route
                  key={id}
                  path={path}
                  element={<WorkspaceRouteGate id={id}>{elements[id]}</WorkspaceRouteGate>}
                />
              ))}
              <Route path="*" element={<WorkspaceLanding />} />
            </Routes>
          </main>
        </div>
      </ProjectScopeProvider>

      <ToastContainer />
    </div>
  )
}
