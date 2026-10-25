import type { ReactNode } from "react"
import { Button } from "@/shared/ui/button"
import { isProjectUnavailableError, useProjectScope } from "@/domains/projects"
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
