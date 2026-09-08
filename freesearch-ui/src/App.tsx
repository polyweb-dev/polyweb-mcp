import type { ReactNode } from "react"
import { Navigate, Route, Routes } from "react-router"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { Sidebar, type TabId } from "@/components/layout/Sidebar"
import { SearchPlayground } from "@/components/search/SearchPlayground"
import { ProviderMatrix } from "@/components/providers/ProviderMatrix"
import { RoutingEngine } from "@/components/routing/RoutingEngine"
import { QuotaAnalytics } from "@/components/quota/QuotaAnalytics"
import { ActivityStream } from "@/components/activity/ActivityStream"
import { SettingsView } from "@/components/settings/SettingsView"
import { ToastContainer } from "@/components/common/ToastContainer"

const workspaceRoutes: Array<{
  id: TabId
  path: string
  element: ReactNode
}> = [
  { id: "playground", path: "/playground", element: <SearchPlayground /> },
  { id: "providers", path: "/providers", element: <ProviderMatrix /> },
  { id: "routing", path: "/routing", element: <RoutingEngine /> },
  { id: "quotas", path: "/usage", element: <QuotaAnalytics /> },
  { id: "activity", path: "/activity", element: <ActivityStream /> },
  { id: "settings", path: "/settings", element: <SettingsView /> },
]

function DashboardContent() {
  return (
    <div
      className="flex min-h-screen flex-row font-sans"
      style={{ background: "var(--surface)", color: "var(--text)" }}
    >
      <Sidebar />

      <main className="min-w-0 flex-1 px-6 py-8 pt-16 sm:px-8 md:pt-8 lg:px-12">
        <Routes>
          <Route path="/" element={<Navigate to="/playground" replace />} />
          {workspaceRoutes.map(({ id, path, element }) => (
            <Route key={id} path={path} element={element} />
          ))}
          <Route path="*" element={<Navigate to="/playground" replace />} />
        </Routes>
      </main>

      <ToastContainer />
    </div>
  )
}

function App() {
  return (
    <FreeSearchProvider>
      <DashboardContent />
    </FreeSearchProvider>
  )
}

export default App
