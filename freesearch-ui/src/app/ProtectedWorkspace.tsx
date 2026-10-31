import type { ReactNode } from "react"
import { Navigate, useLocation } from "react-router"
import { useAuth } from "@/domains/auth"
import { ProjectsProvider } from "@/domains/projects"
import { RestoreStatusView } from "./RestoreStatusView"
import { loginPathFor } from "./routes"
import { WorkspaceControls } from "./WorkspaceControls"

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
 * account's results. The projects provider sits outermost: it owns the live
 * system access descriptor that the control-plane flags derive from.
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
    <ProjectsProvider key={account.id} accountId={account.id}>
      <WorkspaceControls accountId={account.id}>{children}</WorkspaceControls>
    </ProjectsProvider>
  )
}
