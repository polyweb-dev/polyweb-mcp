import { useEffect, useRef } from "react"
import type { ReactNode } from "react"
import { Button } from "@/shared/ui/button"
import { isProjectUnavailableError, useProjectScope, useProjects } from "@/domains/projects"
import { ProjectUnavailableView } from "./ProjectUnavailableView"

/**
 * Gate of one project-scoped page.
 *
 * An access descriptor that fails with 404 renders the neutral unavailable
 * view — and because the page below never mounts, no members request or other
 * project-scoped read is sent for an inaccessible project. A transient failure
 * (network, 5xx, a lost poll) instead offers a retry of the access read.
 */
export function ProjectScopeGate({ children }: { children: ReactNode }) {
  const { accessState, refreshAccess } = useProjectScope()
  const { reloadProjects } = useProjects()

  // Once access resolves to denied/not-found, refresh the list once so the
  // revoked project drops from it without a full page reload.
  const denied =
    accessState.status === "error" && isProjectUnavailableError(accessState.error)
  const wasDenied = useRef(false)
  useEffect(() => {
    if (denied && !wasDenied.current) void reloadProjects()
    wasDenied.current = denied
  }, [denied, reloadProjects])

  if (accessState.status === "error") {
    if (isProjectUnavailableError(accessState.error)) return <ProjectUnavailableView />
    return (
      <div role="alert" className="flex flex-col gap-3">
        <p className="text-[13px] text-[var(--muted)]">The project could not be loaded.</p>
        <div>
          <Button type="button" onClick={() => refreshAccess()}>
            Retry
          </Button>
        </div>
      </div>
    )
  }
  if (accessState.status === "loading") {
    return (
      <p role="status" className="text-[13px] text-[var(--muted)]">
        Loading project…
      </p>
    )
  }
  return <>{children}</>
}
