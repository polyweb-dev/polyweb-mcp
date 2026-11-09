import { useCallback, useMemo } from "react"
import { PROJECT_PERMISSIONS, hasPermission, useProjectScope } from "@/domains/projects"
import { getProjectProviderView } from "@/domains/providers"
import type { ProjectProvider } from "@/domains/providers"
import { getProjectOrder } from "@/domains/routing"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import { PlaygroundPersistGate } from "@/store/PlaygroundPersistGate"
import type { PlaygroundScope } from "../model/usePlaygroundController"
import { projectOrderProviders } from "../model/projectOrderProviders"
import { PlaygroundPage } from "./PlaygroundPage"

const NO_PROVIDERS: readonly ProjectProvider[] = []

/**
 * Playground page of the URL project.
 *
 * The project's playground store and execution scope live one level up
 * (`ProjectPlaygroundScope`), so leaving the page keeps an in-flight request;
 * this page waits for the store's rehydration only. The provider view loads
 * with the scoped-resource pattern under `accountId:projectId`; without
 * `providers.read` the picker offers Auto (and All for search) only.
 */
export function ProjectPlaygroundPage({ accountId }: { accountId: string }) {
  const { projectId, accessState } = useProjectScope()
  const access = accessState.status === "ready" ? accessState.data : null
  const canReadProviders = hasPermission(access, PROJECT_PERMISSIONS.providersRead)
  const scopeKey = `${accountId}:${projectId}`
  const load = useCallback(async (signal: AbortSignal) => {
    const [view, order] = await Promise.all([
      getProjectProviderView(projectId, signal),
      getProjectOrder(projectId, signal),
    ])
    return projectOrderProviders(order, view.providers)
  }, [projectId])
  const view = useScopedResource({ scopeKey, load, enabled: canReadProviders })

  const scope = useMemo<PlaygroundScope>(
    () => ({
      projectId,
      providers: view.status === "ready" && canReadProviders ? view.data.providers : NO_PROVIDERS,
      orderedProviders: view.status === "ready" && canReadProviders ? view.data.byOperation : undefined,
      providersLoading: canReadProviders && view.status === "loading",
      providersReady: canReadProviders && view.status === "ready",
      providersError: canReadProviders && view.status === "error",
      retryProviders: () => {
        void view.reload()
      },
      canSearch: hasPermission(access, PROJECT_PERMISSIONS.searchExecute),
      canFetch: hasPermission(access, PROJECT_PERMISSIONS.fetchExecute),
    }),
    [view, canReadProviders, access, projectId]
  )

  return (
    <PlaygroundPersistGate>
      <PlaygroundPage scope={scope} />
    </PlaygroundPersistGate>
  )
}
