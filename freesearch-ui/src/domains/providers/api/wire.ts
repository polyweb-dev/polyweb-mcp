export type BackendBreakerState = "closed" | "open" | "half_open"
export type BackendHealth = "healthy" | "degraded" | "unavailable" | "unknown"
export type BackendSecretPresence = "configured" | "missing" | "keyless_public"
export type BackendSecretSource = "environment" | "dotenv" | "keyring" | "none"

export type BackendCircuitBreaker = {
  state: BackendBreakerState
  updated_at: string
}

export interface BackendProviderStatus {
  provider_id: string
  enabled: boolean
  priority: number
  health: BackendHealth | null
  circuit_breaker: BackendCircuitBreaker
  latency_p95_ms: number | null
  secret_presence: BackendSecretPresence
  free_tier_estimates: Record<string, string>
  reset_schedule: string | null
}

export interface BackendProviderTest {
  provider: string
  ok: boolean
  status: BackendHealth
  latency_ms: number
  checked_at: string
  detail: string | null
}

export interface BackendSecretStatus {
  provider: string
  presence: BackendSecretPresence
  fingerprint: string | null
  updated_at: string | null
  source: BackendSecretSource
}
