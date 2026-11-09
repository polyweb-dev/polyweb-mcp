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

/** Decode a provider-wide entry. A successful null response means no entry. */
export function decodeManualQuota(value: unknown): BackendManualQuota | null {
  if (value === null) return null
  if (typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Invalid manual quota response")
  }
  const row = value as Record<string, unknown>
  const required = ["provider", "billing_start", "billing_end", "allowance", "current_usage"] as const
  const optional = ["remaining", "remaining_percent", "source", "note", "updated_at"] as const
  for (const key of required) {
    if (typeof row[key] !== "string") throw new Error("Invalid manual quota response")
  }
  for (const key of optional) {
    if (row[key] !== undefined && row[key] !== null && typeof row[key] !== "string") {
      throw new Error("Invalid manual quota response")
    }
  }
  return row as unknown as BackendManualQuota
}
