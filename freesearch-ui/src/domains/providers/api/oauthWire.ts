/** OAuth device-flow pairing state per provider (frozen backend contract). */
export type BackendOAuthFlowStatus = "pending" | "ready" | "expired" | "denied" | "unpaired"

export interface BackendOAuthDeviceCode {
  provider: string
  user_code: string
  verification_uri: string
  verification_uri_complete: string | null
  expires_in: number
  interval: number
}

export interface BackendOAuthStatus {
  provider: string
  status: BackendOAuthFlowStatus
  expires_in: number | null
}
