import type { ReactNode } from "react"
import { Navigate, useLocation } from "react-router"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { useAuth } from "@/domains/auth"
import { ProjectsProvider } from "@/domains/projects"
import { canEditControls, canReadControls } from "./permissions"
import { RestoreStatusView } from "./RestoreStatusView"
import { loginPathFor } from "./routes"

const RESTORE_FAILURE = "The account session could not be restored."

/**
 * Session gate of the protected workspace.
 *
 * The gate completes one cookie restore and one `GET /users/me` before it mounts
 * any business provider, so a protected page never flashes for an anonymous
 * visitor and no control read starts without an account. A network or server
 * failure shows a retry view instead of a false anonymous session.
 *
 * The confirmed account UUID keys the provider tree, so an account switch
 * remounts the store and the domain state instead of reusing the previous
 * account's results.
 */
export function ProtectedWorkspace({ children }: { children: ReactNode }) {
  const { status, account, error, restore } = useAuth()
  const location = useLocation()

  if (status === "restoring") {
    return (
      <RestoreStatusView
        live="status"
        title="Restoring your session"
        detail="Checking your account session."
      />
    )
  }

  if (status === "unavailable") {
    return (
      <RestoreStatusView
        live="alert"
        title="The account session is unavailable"
        detail={error ?? RESTORE_FAILURE}
        onRetry={() => void restore()}
      />
    )
  }

  if (account === null) {
    return <Navigate to={loginPathFor(location.pathname)} replace />
  }

  return (
    <FreeSearchProvider
      key={account.id}
      accountId={account.id}
      canReadControls={canReadControls(account.role)}
      canEditControls={canEditControls(account.role)}
    >
      <ProjectsProvider accountId={account.id}>{children}</ProjectsProvider>
    </FreeSearchProvider>
  )
}
