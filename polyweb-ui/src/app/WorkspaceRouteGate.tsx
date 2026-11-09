import type { ReactNode } from "react"
import { Navigate } from "react-router"
import { useProjects } from "@/domains/projects"
import { WORKSPACE_ENTRY_PATH, canAccessRoute, isGatedRoute, type TabId } from "./routes"
import { WorkspaceAccessGate } from "./WorkspaceAccessGate"

/**
 * Route gate of one global workspace route.
 *
 * It uses the same helper as the navigation filter, so a hidden link and a
 * rejected direct URL can never disagree. An open route renders at once; a
 * gated route waits for the system access descriptor, then renders or
 * redirects an unauthorized direct URL to the workspace entry.
 */
export function WorkspaceRouteGate({ id, children }: { id: TabId; children: ReactNode }) {
  const { systemAccess } = useProjects()
  if (!isGatedRoute(id)) return <>{children}</>
  return (
    <WorkspaceAccessGate>
      {canAccessRoute(id, systemAccess) ? children : <Navigate to={WORKSPACE_ENTRY_PATH} replace />}
    </WorkspaceAccessGate>
  )
}
