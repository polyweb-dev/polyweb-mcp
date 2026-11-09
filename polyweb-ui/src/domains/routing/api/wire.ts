export type BackendRoutingMode = "auto" | "prefer" | "require" | "fanout"

export interface BackendRoutingPreference {
  mode: BackendRoutingMode
  providers: string[]
  allow_fallback: boolean
}

export interface BackendRoutingConfig {
  fallback_policy: "chained" | "first_only"
  max_attempts: number
}
