import type { ReactNode } from "react"
import type { ProviderTypeView } from "@/domains/providers"
import type { OrderOperation, OrderProvider } from "@/domains/routing"
import type { PoolOperation } from "@/domains/vault"
import type { ProjectProvidersController } from "./useProjectProvidersController"

export interface ProviderOrderContext {
  projectId: string
  revision?: number
  providers: readonly ProviderTypeView[]
  controller: ProjectProvidersController
  canConfigure: boolean
  canManagePrivate: boolean
  owner?: string | null
  isOwner?: boolean
  canEditSystem?: boolean
  addCapacity?: () => void
  renderPool?: (provider: OrderProvider, operation: OrderOperation) => ReactNode
  renderMenu?: (provider: OrderProvider) => ReactNode
  poolOperations?: (provider: string) => readonly PoolOperation[] | undefined
  changePoolOperation?: (provider: string, operation: PoolOperation, enabled: boolean) => void
  operationPending?: boolean
}
