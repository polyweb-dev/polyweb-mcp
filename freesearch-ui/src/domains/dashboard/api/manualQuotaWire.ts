/**
 * Manually entered billing window for providers without a vendor balance
 * endpoint (Brave first, reusable for Exa/Parallel). Decimal-as-string
 * allowance/used stay verbatim; ISO YYYY-MM-DD billing bounds.
 */
export interface BackendManualQuota {
  provider: string
  billing_start: string
  billing_end: string
  allowance: string
  current_usage: string
  remaining?: string | null
  remaining_percent?: string | null
  source?: string | null
  note?: string | null
  updated_at?: string | null
}

export interface BackendManualQuotaPayload {
  billing_start: string
  billing_end: string
  allowance: string
  current_usage: string
  note?: string | null
}
