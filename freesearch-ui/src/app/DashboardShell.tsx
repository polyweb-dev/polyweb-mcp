import type { ReactNode } from "react"
import { Navigate, Route, Routes } from "react-router"
import { Sidebar } from "@/app/layout/Sidebar"
import { StatusBar } from "@/app/layout/StatusBar"
import { SearchPlayground } from "@/components/search/SearchPlayground"
import { RoutingEngine } from "@/components/routing/RoutingEngine"
import { QuotaAnalytics } from "@/components/quota/QuotaAnalytics"
import { ActivityStream } from "@/components/activity/ActivityStream"
import { SettingsView } from "@/components/settings/SettingsView"
import { ToastContainer } from "@/components/common/ToastContainer"
import { workspaceRoutes, type TabId } from "./routes"

const routeElements: Record<TabId, ReactNode> = {
  playground: <SearchPlayground />,
  routing: <RoutingEngine />,
  quotas: <QuotaAnalytics />,
  activity: <ActivityStream />,
  settings: <SettingsView />,
}

export function DashboardShell() {
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
            {workspaceRoutes.map(({ id, path }) => (
              <Route key={id} path={path} element={routeElements[id]} />
            ))}
            <Route path="*" element={<Navigate to="/playground" replace />} />
          </Routes>
        </main>
        {/* StatusBar owns its sticky bottom-0 in-flow placement. */}
        <StatusBar />
      </div>

      <ToastContainer />
    </div>
  )
}
