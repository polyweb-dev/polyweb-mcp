import { MinusCircle, Pencil } from "lucide-react"
import type { ProjectPool, ProviderOwner } from "@/domains/projects"
import type { ProviderTypeView } from "@/domains/providers"
import type { PoolOperation } from "@/domains/vault"
import { ApiError } from "@/shared/api/http"
import type { ScopedResource } from "@/shared/lib/useScopedResource"
import { Button } from "@/shared/ui/button"
import { EmptyState } from "@/shared/ui/EmptyState"
import { RowActionsMenu } from "@/shared/ui/RowActionsMenu"
import { identityDetailLabel } from "@/shared/lib/identity"
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

function renderReadyContent(props: Omit<Props, "pools"> & { pools: ProjectPool[]; providers: ProviderTypeView[] }) {
  const { projectId, revision, providers, pools, owner, isOwner, canConfigure, missing } = props
  const ownerEntry = owner.status === "ready" ? owner.data : null
  const ownerContact = ownerEntry === null || ownerEntry === undefined ? null : identityDetailLabel(ownerEntry)
  return <>
    <ProviderOrderSection key={projectId} context={{
      projectId, revision, providers, canConfigure, ownerContact, isOwner,
      canEditSystem: props.canEditSystem, addCapacity: missing.length > 0 ? () => props.add() : undefined,
      poolOperations: (provider) => pools.find((pool) => pool.provider_type === provider)?.operations,
      changePoolOperation: (provider, operation, enabled) => {
        const pool = pools.find((entry) => entry.provider_type === provider)
        if (pool) props.changeOperation(pool, operation, enabled)
      },
      operationPending: props.operationPending,
      renderPool: (item, operation) => <ProjectPoolCell pool={pools.find((pool) => pool.provider_type === item.provider)} operation={operation} />,
      renderMenu: (item) => {
        if (!isOwner) return null
        const pool = pools.find((entry) => entry.provider_type === item.provider)
        if (pool !== undefined) {
          return <RowActionsMenu label={`Actions for ${item.name}`} actions={[
            { key: "edit", label: "Edit pool", icon: Pencil, onSelect: () => props.edit(pool) },
            { key: "unassign", label: "Unassign", icon: MinusCircle, danger: true, onSelect: () => props.unassign(pool) },
          ]} />
        }
        return null
      },
    }} />
    <ProvidersWithoutCapacity providers={missing} isOwner={isOwner} onAdd={props.add} />
    {providers.length === 0 && pools.length === 0 && <EmptyState title="No providers yet" description={isOwner
      ? "Add provider capacity to use providers" : `No provider has capacity yet. Ask ${ownerContact ?? "the provider owner"} to add it`} />}
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
