export type BackendRoutingMode = "auto" | "prefer" | "require"

export interface BackendRoutingPreference {
  mode: BackendRoutingMode
  providers: string[]
  allow_fallback: boolean
}

export interface BackendRoutingConfig {
  fallback_policy: "chained" | "first_only"
  cost_optimization_preset: "balanced" | "free_first"
  max_attempts: number
}
