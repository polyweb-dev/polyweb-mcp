import { useMemo } from "react"
import type { ReactNode } from "react"
import { Navigate, Route, Routes, useLocation } from "react-router"
import { Sidebar } from "@/app/layout/Sidebar"
import { ProjectWorkspace } from "./ProjectWorkspace"
import { ProjectsPage } from "@/features/projects/ui/ProjectsPage"
import { QuotaAnalytics } from "@/features/quota/ui/QuotaAnalytics"
import { SettingsView } from "@/features/system-providers/ui/SettingsView"
import { AccountPage } from "@/features/auth/ui/AccountPage"
import { KeysPoolsPage } from "@/features/vault/ui/KeysPoolsPage"
import { ToastContainer } from "@/components/common/ToastContainer"
import { useAuth } from "@/domains/auth"
import { ProjectScopeProvider } from "@/domains/projects"
import {
  LEGACY_GLOBAL_REDIRECTS,
  LEGACY_SECTION_PATHS,
  legacyKeysDestination,
  projectIdFromPath,
  workspaceRoutes,
  type TabId,
} from "./routes"
import { WorkspaceAccessGate } from "./WorkspaceAccessGate"
import { WorkspaceLanding } from "./WorkspaceLanding"
import { WorkspaceRouteGate } from "./WorkspaceRouteGate"
import { AccountTabs } from "./AccountTabs"

function routeElements(adminEmail: string, accountId: string): Record<TabId, ReactNode> {
  return {
    quotas: <QuotaAnalytics />,
    settings: <SettingsView />,
    systemCredentials: <Navigate to="/account/keys" replace />,
    systemCapacity: <Navigate to="/account/keys" replace />,
    projects: (
      <WorkspaceAccessGate>
        <ProjectsPage defaultAdminEmail={adminEmail} />
      </WorkspaceAccessGate>
    ),
    account: <AccountTabs page="profile"><AccountPage /></AccountTabs>,
    accountKeys: <AccountTabs page="keys"><KeysPoolsPage key={accountId} /></AccountTabs>,
  }
}

/**
 * Route gate and project scope of the workspace.
 *
 * Every gate reads effective permissions: global routes the system access
 * descriptor, project sections the project access descriptor. The project
 * scope sits above the sidebar and the page, keyed by `accountId:projectId`
 * from the URL, so both read one access state. `/` and unknown paths land on
 * the last valid project, else the project list; the former global
 * section paths land on that project's section. Retired global pages and
 * provider credentials tabs redirect to their replacement pages.
 */
export function DashboardShell() {
  const { account } = useAuth()
  const { pathname, search } = useLocation()
  const keysDestination = legacyKeysDestination(pathname, search)
  const accountId = account?.id ?? ""
  const adminEmail = account?.email ?? ""
  const elements = useMemo(() => routeElements(adminEmail, accountId), [adminEmail, accountId])

  return (
    <div
      className="flex min-h-screen flex-row font-sans"
      style={{ background: "var(--surface)", color: "var(--text)" }}
    >
      <ProjectScopeProvider accountId={accountId} projectId={projectIdFromPath(pathname)}>
        <Sidebar />

        <div className="flex min-w-0 flex-1 flex-col">
          <main className="mx-auto flex w-full min-w-0 max-w-[1400px] flex-1 flex-col px-6 py-6 pt-16 sm:px-8 md:pt-6 lg:px-10">
            {keysDestination !== null ? <Navigate to={keysDestination} replace /> : <Routes>
              <Route path="/" element={<WorkspaceLanding />} />
              {Object.entries(LEGACY_GLOBAL_REDIRECTS).map(([path, target]) => (
                <Route key={path} path={path} element={<Navigate to={target} replace />} />
              ))}
              {Object.entries(LEGACY_SECTION_PATHS).map(([path, section]) => (
                <Route key={path} path={path} element={<WorkspaceLanding section={section} />} />
              ))}
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
            </Routes>}
          </main>
        </div>
      </ProjectScopeProvider>

      <ToastContainer />
    </div>
  )
}
