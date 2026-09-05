import { useState } from "react"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { Header, type TabId } from "@/components/layout/Header"
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
      className="min-h-screen flex flex-col font-sans"
      style={{ background: "var(--surface)", color: "var(--text)" }}
    >
      <Header activeTab={activeTab} onSelectTab={setActiveTab} />

      <main className="flex-1 w-full max-w-[1600px] mx-auto px-6 sm:px-8 lg:px-12 py-8">
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
