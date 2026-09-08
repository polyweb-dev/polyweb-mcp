import { useState } from "react"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { Sidebar, type TabId } from "@/components/layout/Sidebar"
import { SearchPlayground } from "@/components/search/SearchPlayground"
import { ProviderMatrix } from "@/components/providers/ProviderMatrix"
import { RoutingEngine } from "@/components/routing/RoutingEngine"
import { QuotaAnalytics } from "@/components/quota/QuotaAnalytics"
import { ActivityStream } from "@/components/activity/ActivityStream"
import { SettingsView } from "@/components/settings/SettingsView"
import { ToastContainer } from "@/components/common/ToastContainer"

function DashboardContent() {
  const [activeTab, setActiveTab] = useState<TabId>("playground")

  return (
    <div
      className="flex min-h-screen flex-row font-sans"
      style={{ background: "var(--surface)", color: "var(--text)" }}
    >
      <Sidebar activeTab={activeTab} onSelectTab={setActiveTab} />

      <main className="min-w-0 flex-1 px-6 py-8 pt-16 sm:px-8 md:pt-8 lg:px-12">
        {activeTab === "playground" && <SearchPlayground />}
        {activeTab === "providers" && <ProviderMatrix />}
        {activeTab === "routing" && <RoutingEngine />}
        {activeTab === "quotas" && <QuotaAnalytics />}
        {activeTab === "activity" && <ActivityStream />}
        {activeTab === "settings" && <SettingsView />}
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
