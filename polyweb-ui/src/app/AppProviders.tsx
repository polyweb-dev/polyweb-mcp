import type { ReactNode } from "react"
import { AuthProvider } from "@/domains/auth"
import { TooltipProvider } from "@/shared/ui/tooltip"

/**
 * Root provider composition.
 *
 * Auth sits above every business provider, so the session gate can mount and
 * unmount the workspace providers with the confirmed account. The playground
 * store and the domain providers now live below that gate, inside
 * `ProtectedWorkspace`.
 */
export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <AuthProvider>
      <TooltipProvider>{children}</TooltipProvider>
    </AuthProvider>
  )
}
