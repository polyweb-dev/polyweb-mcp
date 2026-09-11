import type { ReactNode } from "react"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { TooltipProvider } from "@/shared/ui/tooltip"

/** Root provider composition: business state above tooltip behavior. */
export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <FreeSearchProvider>
      <TooltipProvider>{children}</TooltipProvider>
    </FreeSearchProvider>
  )
}
