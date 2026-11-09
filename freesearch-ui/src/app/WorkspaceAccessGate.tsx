import type { ReactNode } from "react"
import { useProjects } from "@/domains/projects"
import { Button } from "@/shared/ui/button"

export const WORKSPACE_LOADING_MESSAGE = "Loading workspace…"
export const WORKSPACE_LOAD_FAILURE_MESSAGE = "The workspace could not be loaded."

/**
 * Gate of every surface that needs the system access descriptor or the
 * project list.
 *
 * While they load, the gate shows a status instead of redirecting, so a
 * permitted deep link never bounces. A failed load shows an alert with Retry
 * instead of hiding the UI.
 */
export function WorkspaceAccessGate({ children }: { children: ReactNode }) {
  const { availability, reloadProjects } = useProjects()

  if (availability === "loading") {
    return (
      <p role="status" className="text-[13px] text-[var(--muted)]">
        {WORKSPACE_LOADING_MESSAGE}
      </p>
    )
  }
  if (availability === "unavailable") {
    return (
      <div
        role="alert"
        className="max-w-sm rounded-md border border-[var(--border-subtle)] bg-[var(--elevated)] p-4"
      >
        <p className="text-[13px] text-[var(--text-strong)]">{WORKSPACE_LOAD_FAILURE_MESSAGE}</p>
        <div className="mt-3">
          <Button type="button" variant="outline" onClick={() => void reloadProjects()}>
            Retry
          </Button>
        </div>
      </div>
    )
  }
  return <>{children}</>
}
