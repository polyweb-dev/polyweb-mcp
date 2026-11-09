import type { ReactNode } from "react"
import { ProjectExecutionProvider } from "@/domains/execution/state/ProjectExecutionProvider"
import { catalogNameOf } from "@/domains/providers"
import { useNotifications } from "@/shared/notifications/useNotifications"
import { AppStoreProvider } from "@/store/AppStoreProvider"

/**
 * Project-level playground scope: the project's playground store and its
 * execution scope. It wraps every section of one project, so an in-flight
 * search or fetch survives a switch to another section and back. The parent
 * keys it by `accountId:projectId`: a project switch unmounts it, which aborts
 * the old project's request and settles its pending state.
 */
export function ProjectPlaygroundScope({
  accountId,
  projectId,
  children,
}: {
  accountId: string
  projectId: string
  children: ReactNode
}) {
  const { showToast } = useNotifications()
  return (
    <AppStoreProvider accountId={accountId} projectId={projectId}>
      <ProjectExecutionProvider
        projectId={projectId}
        showToast={showToast}
        catalogNameOf={catalogNameOf}
      >
        {children}
      </ProjectExecutionProvider>
    </AppStoreProvider>
  )
}
