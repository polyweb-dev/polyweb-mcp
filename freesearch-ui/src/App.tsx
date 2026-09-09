import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { DashboardContent } from "@/components/layout/DashboardContent"
import { TooltipProvider } from "@/components/ui/tooltip"

function App() {
  return (
    <FreeSearchProvider>
      <TooltipProvider>
        <DashboardContent />
      </TooltipProvider>
    </FreeSearchProvider>
  )
}

export default App
