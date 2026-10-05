/**
 * Credit-unit (CRD) limit domain types. One CRD is USD 0.001 of priced native use. Every amount stays an exact decimal string end to end: the
 * decoders keep the wire text verbatim and the display layer rounds for presentation only. Never convert an amount to a float for arithmetic.
 * Enum text that the payload does not recognize falls back to "unknown".
 */

export type CRDState = "finite" | "unmetered" | "unavailable" | "unknown"
export type CRDOperation = "search" | "fetch"
export type CRDAuthMode = "keyless" | "keyed" | "unknown"
export type CRDConfidence = "authoritative" | "observed" | "estimated" | "unknown"
export type CRDFundingMode = "prepaid" | "recurring" | "postpaid" | "no_budget" | "unknown"
export type CRDResetRule = "monthly_first" | "vendor_period" | "daily_vendor" | "daily_estimate" | "never" | "unknown"
export type CRDTier = "free" | "paid" | "unknown"
export type CRDNativeUnit = "REQUEST" | "CREDIT" | "USD" | "FREE" | "unknown"
export type CRDRateWindow = "1s" | "1m" | "1h" | "1d" | "unknown"
/** Rate bars exist for these windows only; `1s` and `1m` stay detail text. */
export type CRDBarWindow = "1h" | "1d"
export type CRDRateScope = "org" | "team" | "key" | "ip" | "unknown"
export type CRDRateUnit = "requests" | "urls"
export type CRDRateKind = "rate" | "free_daily_allowance"
export type CRDBudgetModel = "none" | "requests" | "credits" | "usd" | "unknown"
export type CRDExhaustAction = "402" | "stop" | "bill" | "unknown"

/** One exact credit-unit capacity view of one operation. */
export interface CRDView {
  state: CRDState
  operation: CRDOperation
  remaining_crd: string | null
  local_remaining_crd: string | null
  request_cost_crd: string | null
  shared_pool_id: string | null
  possible_standard_calls: string | null
  price_version: string | null
  priced: boolean
}

/** One applicable free or paid subpool of a provider account. */
export interface TierBalance {
  pool_id: string
  tier: CRDTier
  native_unit: CRDNativeUnit
  native_remaining: string | null
  native_allowance: string | null
  remaining_crd: string | null
  allowance_crd: string | null
  reset_rule: CRDResetRule
  reset_at: string | null
  funding_mode: CRDFundingMode
  source: string
  confidence: CRDConfidence
  transport_available: boolean
  label: string | null
}

/** Hourly or daily rate capacity shown outside collapsed detail. */
export interface RateProgressView {
  bucket_id: string
  operation: CRDOperation
  window: CRDBarWindow
  unit: CRDRateUnit
  remaining: string | null
  limit: string | null
  reset_at: string | null
  source: string
  confidence: CRDConfidence
  kind: CRDRateKind
  stale: boolean
  enforceable: boolean
}

/** Durable native funds shared by one or more operation views. */
export interface NativePool {
  pool_id: string
  provider: string
  auth_mode: string
  native_unit: string
  remaining: string | null
  allowance: string | null
  actual_spend_usd: string | null
  source: string
  confidence: string
  reset_at: string | null
  observed_at: string | null
  version: number
  credential_generation: number
  next_sync_at: string | null
  stale: boolean
  manual_anchor: boolean
}

/** One documented vendor rate window (detail text, never a bar for 1s/1m). */
export interface LimitRateWindow {
  bucket_id: string; limit: string; window: CRDRateWindow; scope: CRDRateScope; unit: CRDRateUnit
  remaining: string | null; reset_at: string | null; source: string; confidence: string
}

export interface LimitRate { windows: LimitRateWindow[]; published: boolean }

export interface LimitBudget {
  model: CRDBudgetModel
  free_allowance: string | null
  allowance_unit: string
  allowance_period: string | null
  cost_per_1k: string | null
  standard_native_cost: string
  usd_per_call: string | null
  on_exhausted: CRDExhaustAction
  usage_api: string | null
  priced: boolean
}

export interface CRDConversionProfile {
  reference_usd_per_crd: string; native_usd_per_unit: string | null; cost_basis: string
  price_version: string; source: string; estimated: boolean
}

/** Catalog record: one provider, one operation, one auth mode. */
export interface LimitRecord {
  provider: string; operation: CRDOperation; auth_mode: string
  supported: boolean; transport_available: boolean; native_pool_id: string | null
  rate: LimitRate | null; budget: LimitBudget | null; conversion_profile: CRDConversionProfile
  plan_name: string | null; usage_url: string | null; version: number
}

/** Detail-only native, USD, plan, and rate information for one rail. */
export interface ProviderLimitDetail {
  plan_name: string | null
  native_unit: string | null
  native_balance: string | null
  native_allowance: string | null
  usd_per_call: string | null
  actual_spend_usd: string | null
  reset_at: string | null
  reset_rule: CRDResetRule
  usage_url: string | null
  source: string
  confidence: CRDConfidence
  last_sync_at: string | null
  stale: boolean
  price_version: string
  crd_split_note: string | null
  rate_windows: LimitRateWindow[]
  tier_split_known: boolean
  aggregate_pool_id: string | null
}

/**
 * Operator grant of search and fetch credit units for one period.
 * `auth_mode` selects the endpoint path only; the request body carries the version, the period, and the two amounts.
 */
export interface CRDGrantPayload {
  auth_mode?: string; version: number; period_start: string; period_end: string
  search_crd: string; fetch_crd: string
}

/** Stored grant state for one provider, auth mode, and period. */
export interface CRDGrantsSummary {
  provider: string
  auth_mode: string
  period_start: string
  period_end: string
  version: number
  search_granted_crd: string
  search_consumed_crd: string
  search_reserved_crd: string
  fetch_granted_crd: string
  fetch_consumed_crd: string
  fetch_reserved_crd: string
}

/** Credit-unit use aggregated for one provider and operation. */
export interface CRDUsageTotal {
  provider: string; operation: CRDOperation; normalized_crd: string
  attempt_count: number; volume_count: number
}

/** One immutable balance-change or denial record. */
export interface LimitAuditEvent {
  event_id: string
  provider: string
  auth_mode: string
  operation: string | null
  pool_id: string | null
  observed_at: string
  source: string
  reason: string
  old_native: string | null
  new_native: string | null
  old_crd: string | null
  new_crd: string | null
  crd_debit: string | null
  native_debit: string | null
  actual_usd: string | null
  confidence: CRDConfidence
  local_attempt_id: string | null
  detail: Record<string, unknown>
}

export interface LimitHistoryPage { events: LimitAuditEvent[]; next_cursor: string | null }

/** Limit state of one provider under one auth mode. */
export interface ProviderAuthLimits {
  auth_mode: CRDAuthMode
  transport_available: boolean
  search: LimitRecord | null
  fetch: LimitRecord | null
  free_tiers: TierBalance[]
  paid_tiers: TierBalance[]
  unknown_tiers: TierBalance[]
  tier_split_known: boolean
  aggregate_pool: NativePool | null
  crd_views: CRDView[]
  rate_progress: RateProgressView[]
  grants: CRDGrantsSummary | null
  detail: ProviderLimitDetail | null
}

/** Dashboard payload for one provider: both auth modes and their views. */
export interface ProviderLimits {
  provider: string; active_auth_mode: CRDAuthMode; auths: ProviderAuthLimits[]
  documented_keyless_operations: string[]; version: number; generated_at: string
}

/** Outcome of one provider sync attempt. */
export interface ProviderLimitsSyncResult {
  provider: string; status: "synced" | "skipped" | "failed"; observed_at: string
  next_sync_at: string | null; error_code: string | null; stale: boolean; changed: boolean; reason: string | null
}

/** Partial catalog update. An omitted field keeps its value; null clears it. */
export interface ProviderLimitPatch {
  backendId: string; authMode: string; operation: CRDOperation; version: number
  rate?: LimitRate; budget?: LimitBudget; conversion_profile?: CRDConversionProfile
  plan_name?: string | null; usage_url?: string | null
}

export interface LimitHistoryQuery { backendId: string; authMode: string; limit?: number; cursor?: string | null }

/** One Free or Paid tier bar. Percentages stay null without an allowance. */
export interface TierBarView {
  tier: "free" | "paid"; poolIds: string[]; remainingCRD: string | null; allowanceCRD: string | null
  percentRemaining: number | null; source: string; confidence: CRDConfidence; resetNotes: string[]
  state: "finite" | "unmetered" | "postpaid" | "unknown"
}

/** One hour or day rate bar. `1s` and `1m` windows never reach this shape. */
export interface RateBarView {
  bucketId: string; operation: CRDOperation; window: CRDBarWindow; unit: CRDRateUnit; kind: CRDRateKind
  remaining: string | null; limit: string | null; resetAt: string | null
  percentRemaining: number | null; confidence: CRDConfidence
}

/** Input of one tier bar: the member balances of that tier only. */
export interface TierBarInput { tier: "free" | "paid"; balances: TierBalance[]; tierSplitKnown: boolean }

/** Input of one rate bar. */
export interface RateBarInput { progress: RateProgressView }
