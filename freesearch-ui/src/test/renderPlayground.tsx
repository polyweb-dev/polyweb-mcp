import type { ReactNode } from "react"
import { MemoryRouter } from "react-router"
import { ProjectScopeContext } from "@/domains/projects/state/context"
import { ProjectPlaygroundPage } from "@/features/playground/ui/ProjectPlaygroundPage"
import { ProjectPlaygroundScope } from "@/features/playground/ui/ProjectPlaygroundScope"
import { NotificationsProvider } from "@/shared/notifications/NotificationsContext"
import { PROJECT_ADMIN_PERMISSIONS, projectScopeValue } from "./accessFixtures"
import { ADMIN_ACCOUNT_ID } from "./authFixtures"
import { PLAYGROUND_PROJECT_ID } from "./projectPlayground"

export interface PlaygroundHarnessProps {
  accountId?: string
  projectId?: string
  permissions?: readonly string[]
  /** `false` renders another project section in place of the playground page. */
  showPage?: boolean
  children?: ReactNode
}

/**
 * The project playground as the workspace mounts it: notifications, a ready
 * project scope, the project-level playground scope keyed by
 * `accountId:projectId` (store and execution), and the playground page (or a
 * stand-in for another section). Extra children render beside the page.
 */
export function PlaygroundHarness({
  accountId = ADMIN_ACCOUNT_ID,
  projectId = PLAYGROUND_PROJECT_ID,
  permissions = PROJECT_ADMIN_PERMISSIONS,
  showPage = true,
  children,
}: PlaygroundHarnessProps) {
  return (
    <NotificationsProvider>
      <MemoryRouter>
        <ProjectScopeContext.Provider value={projectScopeValue(projectId, permissions)}>
        <ProjectPlaygroundScope
          key={`${accountId}:${projectId}`}
          accountId={accountId}
          projectId={projectId}
        >
          {showPage ? (
            <ProjectPlaygroundPage accountId={accountId} />
          ) : (
            <h2>Members</h2>
          )}
          {children}
        </ProjectPlaygroundScope>
        </ProjectScopeContext.Provider>
      </MemoryRouter>
    </NotificationsProvider>
  )
}
