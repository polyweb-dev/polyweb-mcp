export interface RateLimit {
  limit: number | null
  window_seconds: number
}

export interface PoolBudget {
  limit: number
  period: string
}

type BudgetInput = { limit: number; period?: "day" | "week" | "month" }

export type PoolOperation = "search" | "fetch"
export type OperationLimit = number | null | { rate_limit: number | null; rate_window_seconds: number }
export type OperationLimits = Partial<Record<PoolOperation, OperationLimit>>

export interface VaultKey {
  id: string
  provider_type: string
  label: string
  auth_mode: string
  status: string
  generation: number
  created_at: string
  capacity: RateLimit | null
  overcommit: boolean
  contention_mode: "equal" | "ratio"
  pool_count: number
}

export interface KeyPoolInput {
  label: string
  project_id?: string | null
  rate?: Partial<RateLimit>
  budget?: BudgetInput | null
  operations?: PoolOperation[] | null
  operation_limits?: OperationLimits | null
}

export interface KeyPool extends KeyPoolInput {
  id: string
  credential_id: string
  provider_type: string
  project_id: string | null
  rate: RateLimit
  budget: { limit: number; period: "day" | "week" | "month" } | null
  budget_used_usd: number
  operations: PoolOperation[]
  operation_limits: OperationLimits | null
}

export interface VaultKeyDeleteResult {
  deleted_pools: { id: string; project_id: string | null }[]
}

export interface VaultKeyInput {
  provider_type: string
  label: string
  auth_mode?: string
  secret?: string | null
  capacity?: Partial<RateLimit> | null
  overcommit?: boolean
  contention_mode?: "equal" | "ratio"
}

export interface VaultProject {
  id: string
  name: string
  available_providers: string[]
}

export interface VaultOAuthDevice {
  user_code: string
  verification_uri: string
  interval: number
  expires_in: number
}

export interface VaultOAuthStatus {
  status: "pending" | "connected" | "refresh_failed" | "disconnected"
  interval?: number | null
}
