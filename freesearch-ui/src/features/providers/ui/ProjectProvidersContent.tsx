import type { ProjectPool, ProviderOwner } from "@/domains/projects"
import type { ProviderTypeView } from "@/domains/providers"
import type { PoolOperation } from "@/domains/vault"
import { ApiError } from "@/shared/api/http"
import type { ScopedResource } from "@/shared/lib/useScopedResource"
import { Button } from "@/shared/ui/button"
import { EmptyState } from "@/shared/ui/EmptyState"
import { RowActionsMenu } from "@/shared/ui/RowActionsMenu"
import type { ProjectProvidersController } from "../model/useProjectProvidersController"
import { ProjectPoolCell } from "./ProjectPoolCell"
import { ProviderOrderSection } from "./ProviderOrderSection"
import { ProvidersWithoutCapacity } from "./ProvidersWithoutCapacity"

interface Props {
  projectId: string
  revision: number
  controller: ProjectProvidersController
  owner: ScopedResource<ProviderOwner | null>
  pools: ScopedResource<ProjectPool[]>
  missing: ProviderTypeView[]
  isOwner: boolean
  canConfigure: boolean
  canEditSystem: boolean
  reload: () => void
  add: (provider?: string) => void
  edit: (pool: ProjectPool) => void
  unassign: (pool: ProjectPool) => void
  changeOperation: (pool: ProjectPool, operation: PoolOperation, enabled: boolean) => void
  operationPending: boolean
}

function renderPoolMenu({ pool, name, isOwner, edit, unassign }: {
  pool: ProjectPool | undefined
  name: string
  isOwner: boolean
  edit: (pool: ProjectPool) => void
  unassign: (pool: ProjectPool) => void
}) {
  if (!isOwner || !pool) return null
  return <RowActionsMenu label={`Actions for ${name}`} actions={[
    { key: "edit", label: "Edit pool", onSelect: () => edit(pool) },
    { key: "unassign", label: "Unassign", danger: true, onSelect: () => unassign(pool) },
  ]} />
}

function renderReadyContent(props: Omit<Props, "pools"> & { pools: ProjectPool[]; providers: ProviderTypeView[] }) {
  const { projectId, revision, providers, pools, controller, owner, isOwner, canConfigure, missing } = props
  const ownerEmail = owner.status === "ready" ? owner.data?.email : null
  return <>
    <ProviderOrderSection key={projectId} context={{
      projectId, revision, providers, controller, canConfigure, canManagePrivate: false, owner: ownerEmail, isOwner,
      canEditSystem: props.canEditSystem, addCapacity: missing.length > 0 ? () => props.add() : undefined,
      poolOperations: (provider) => pools.find((pool) => pool.provider_type === provider)?.operations,
      changePoolOperation: (provider, operation, enabled) => {
        const pool = pools.find((entry) => entry.provider_type === provider)
        if (pool) props.changeOperation(pool, operation, enabled)
      },
      operationPending: props.operationPending,
      renderPool: (item) => {
        const provider = providers.find((provider) => provider.providerType === item.provider)
        const costs = Object.values(provider?.callCostUsd ?? {})
        return <ProjectPoolCell pool={pools.find((pool) => pool.provider_type === item.provider)} free={costs.length > 0 && costs.every((cost) => cost != null && Number(cost) === 0)} />
      },
      renderMenu: (item) => item.keyless
        ? isOwner && <RowActionsMenu label={`Actions for ${item.name}`} actions={[
          { key: "add", label: "Add a key for higher limits", onSelect: () => props.add(item.provider) },
        ]} />
        : renderPoolMenu({ pool: pools.find((pool) => pool.provider_type === item.provider),
          name: item.name, isOwner, edit: props.edit, unassign: props.unassign }),
    }} />
    <ProvidersWithoutCapacity providers={missing} isOwner={isOwner} onAdd={props.add} />
    {providers.length === 0 && pools.length === 0 && <EmptyState title="No providers yet" description={isOwner
      ? "Add provider capacity to use providers" : `No provider has capacity yet. Ask ${ownerEmail ?? "the provider owner"} to add it`} />}
  </>
}

export function ProjectProvidersContent(props: Props) {
  const { controller, pools, reload } = props
  if (controller.view.status === "loading" || pools.status === "loading") return <p role="status">Loading providers…</p>
  const error = controller.view.status === "error" ? controller.view.error : pools.status === "error" ? pools.error : null
  if (error !== null) return <div role="alert"><p>{error instanceof ApiError && error.status === 404
    ? "Provider capacity is not available yet" : "Providers and capacity could not be loaded"}</p>
    <Button variant="outline" size="form" onClick={reload}>Retry</Button></div>
  if (controller.view.status !== "ready" || pools.status !== "ready") return null
  return renderReadyContent({ ...props, providers: controller.view.data.providers, pools: pools.data })
}
