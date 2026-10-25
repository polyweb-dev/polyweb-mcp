import type { ReactNode } from "react"
import { Navigate, Route, Routes } from "react-router"
import { Sidebar } from "@/app/layout/Sidebar"
import { ProjectWorkspace } from "./ProjectWorkspace"
import { ProjectsPage } from "@/features/projects/ui/ProjectsPage"
import { PROJECTS_PATH } from "./routes"
import { PlaygroundPage } from "@/features/playground/ui/PlaygroundPage"
import { RoutingEngine } from "@/components/routing/RoutingEngine"
import { QuotaAnalytics } from "@/components/quota/QuotaAnalytics"
import { ActivityPage } from "@/features/activity/ui/ActivityPage"
import { SettingsView } from "@/components/settings/SettingsView"
import { AccountPage } from "@/features/auth/ui/AccountPage"
import { AdminUsersPage } from "@/features/users/ui/AdminUsersPage"
import { ToastContainer } from "@/components/common/ToastContainer"
import { useAuth } from "@/domains/auth"
import type { UserRole } from "@/domains/auth"
import { TAB_PATHS, canAccessRoute, workspaceRoutes, type TabId } from "./routes"

const routeElements: Record<TabId, ReactNode> = {
  playground: <PlaygroundPage />,
  routing: <RoutingEngine />,
  quotas: <QuotaAnalytics />,
  activity: <ActivityPage />,
  settings: <SettingsView />,
  account: <AccountPage />,
  adminUsers: <AdminUsersPage />,
}

/**
 * Route gate of the workspace.
 *
 * One permission helper serves the navigation filter and this gate, so a hidden
 * link and a rejected direct URL can never disagree. An unauthorized path
 * redirects to the workspace entry route instead of rendering the page. The
 * legacy root, `/providers`, and unknown-path redirects stay verbatim.
 */
export function DashboardShell() {
  const { account } = useAuth()
  const role: UserRole = account?.role ?? "agent"

  return (
    <div
      className="flex min-h-screen flex-row font-sans"
      style={{ background: "var(--surface)", color: "var(--text)" }}
    >
      <Sidebar />

      <div className="flex min-w-0 flex-1 flex-col">
        <main className="min-w-0 flex-1 px-6 py-8 pt-16 sm:px-8 md:pt-8 lg:px-12 flex flex-col">
          <Routes>
            <Route path="/" element={<Navigate to="/playground" replace />} />
            <Route path="/providers" element={<Navigate to="/settings" replace />} />
            <Route
              path={PROJECTS_PATH}
              element={<ProjectsPage defaultAdminEmail={account?.email ?? ""} />}
            />
            <Route path="/p/:projectId/*" element={<ProjectWorkspace />} />
            {workspaceRoutes.map(({ id, path }) => (
              <Route
                key={id}
                path={path}
                element={
                  canAccessRoute(id, role) ? (
                    routeElements[id]
                  ) : (
                    <Navigate to={TAB_PATHS.playground} replace />
                  )
                }
              />
            ))}
            <Route path="*" element={<Navigate to="/playground" replace />} />
          </Routes>
        </main>
      </div>

      <ToastContainer />
    </div>
  )
}
