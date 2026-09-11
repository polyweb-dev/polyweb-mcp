import { AppProviders } from "@/app/AppProviders"
import { DashboardShell } from "@/app/DashboardShell"

function App() {
  return (
    <AppProviders>
      <DashboardShell />
    </AppProviders>
  )
}

export default App
