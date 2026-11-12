import type { ReactNode } from "react"
import type { ProviderTypeView } from "@/domains/providers"
import type { OrderOperation, OrderProvider } from "@/domains/routing"
import type { PoolOperation } from "@/domains/vault"

export interface ProviderOrderContext {
  projectId: string
  revision?: number
  providers: readonly ProviderTypeView[]
  canConfigure: boolean
  /** Display-only owner contact guidance, e.g. `Ada Lovelace (ada@example.com)`. */
  ownerContact?: string | null
  isOwner?: boolean
  canEditSystem?: boolean
  addCapacity?: () => void
  renderPool?: (provider: OrderProvider, operation: OrderOperation) => ReactNode
  renderMenu?: (provider: OrderProvider) => ReactNode
  poolOperations?: (provider: string) => readonly PoolOperation[] | undefined
  changePoolOperation?: (provider: string, operation: PoolOperation, enabled: boolean) => void
  operationPending?: boolean
}
