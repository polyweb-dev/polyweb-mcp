import type { BudgetPeriod } from "@/shared/lib/budget"
/** Exact decimal USD contracts. Native balances retain their provider units. */

export type UsdState = "finite" | "unmetered" | "unavailable" | "unknown"
export type UsdOperation = "search" | "fetch"
export type UsdAuthMode = "keyless" | "keyed" | "unknown"
export type UsdConfidence = "authoritative" | "observed" | "estimated" | "unknown"
export type UsdFundingMode = "prepaid" | "recurring" | "postpaid" | "no_budget" | "unknown"
export type UsdResetRule = "monthly_first" | "vendor_period" | "daily_vendor" | "daily_estimate" | "never" | "unknown"
export type UsdTier = "free" | "paid" | "unknown"
export type UsdNativeUnit = "REQUEST" | "CREDIT" | "USD" | "FREE" | "unknown"
export type UsdRateWindow = "1s" | "1m" | "1h" | "1d" | "unknown"
/** Rate bars exist for these windows only; `1s` and `1m` stay detail text. */
export type UsdBarWindow = "1h" | "1d"
export type UsdRateScope = "org" | "team" | "key" | "ip" | "unknown"
export type UsdRateUnit = "requests" | "urls"
export type UsdRateKind = "rate" | "free_daily_allowance"
export type UsdBudgetModel = "none" | "requests" | "credits" | "usd" | "unknown"
export type UsdExhaustAction = "402" | "stop" | "bill" | "unknown"

/** One exact credit-unit capacity view of one operation. */
export interface UsdView {
  state: UsdState
  operation: UsdOperation
  remaining_usd: string | null
  local_remaining_usd: string | null
  request_cost_usd: string | null
  shared_pool_id: string | null
  possible_standard_calls: string | null
  price_version: string | null
  priced: boolean
}

/** One applicable free or paid subpool of a provider account. */
export interface TierBalance {
  pool_id: string
  tier: UsdTier
  native_unit: UsdNativeUnit
  native_remaining: string | null
  native_allowance: string | null
  remaining_usd: string | null
  allowance_usd: string | null
  reset_rule: UsdResetRule
  reset_at: string | null
  funding_mode: UsdFundingMode
  source: string
  confidence: UsdConfidence
  transport_available: boolean
  label: string | null
}

/** Hourly or daily rate capacity shown outside collapsed detail. */
export interface RateProgressView {
  bucket_id: string
  operation: UsdOperation
  window: UsdBarWindow
  unit: UsdRateUnit
  remaining: string | null
  limit: string | null
  reset_at: string | null
  source: string
  confidence: UsdConfidence
  kind: UsdRateKind
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
  bucket_id: string; limit: string; window: UsdRateWindow; scope: UsdRateScope; unit: UsdRateUnit
  remaining: string | null; reset_at: string | null; source: string; confidence: string
}

export interface LimitRate { windows: LimitRateWindow[]; published: boolean }

export interface LimitBudget {
  model: UsdBudgetModel
  free_allowance: string | null
  allowance_unit: string
  allowance_period: string | null
  cost_per_1k: string | null
  standard_native_cost: string
  usd_per_call: string | null
  on_exhausted: UsdExhaustAction
  usage_api: string | null
  priced: boolean
}

export interface UsdConversionProfile { native_usd_per_unit: string | null; cost_basis: string
  price_version: string; source: string; estimated: boolean
}

/** Catalog record: one provider, one operation, one auth mode. */
export interface LimitRecord {
  provider: string; operation: UsdOperation; auth_mode: string
  supported: boolean; transport_available: boolean; native_pool_id: string | null
  rate: LimitRate | null; budget: LimitBudget | null; conversion_profile: UsdConversionProfile
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
  reset_rule: UsdResetRule
  usage_url: string | null
  source: string
  confidence: UsdConfidence
  last_sync_at: string | null
  stale: boolean
  price_version: string
  balance_split_note: string | null
  rate_windows: LimitRateWindow[]
  /** Remaining seconds of an active vendor Retry-After delay; zero stays zero. */
  retry_after_seconds?: number | null
  tier_split_known: boolean
  aggregate_pool_id: string | null
}

/**
 * Operator grant of search and fetch credit units for one period.
 * `auth_mode` selects the endpoint path only; the request body carries the version, the period, and the two amounts.
 */
export interface UsdGrantPayload {
  auth_mode?: string; version: number; period: BudgetPeriod
  search_usd: string; fetch_usd: string
}

/** Stored grant state for one provider, auth mode, and period. */
export interface UsdGrantsSummary {
  provider: string
  auth_mode: string
  period: BudgetPeriod
  version: number
  search_granted_usd: string
  search_consumed_usd: string
  search_reserved_usd: string
  fetch_granted_usd: string
  fetch_consumed_usd: string
  fetch_reserved_usd: string
}

/** Credit-unit use aggregated for one provider and operation. */
export interface UsdUsageTotal {
  provider: string; operation: UsdOperation; spend_usd: string
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
  old_usd: string | null
  new_usd: string | null
  debit_usd: string | null
  native_debit: string | null
  actual_usd: string | null
  confidence: UsdConfidence
  local_attempt_id: string | null
  detail: Record<string, unknown>
}

export interface LimitHistoryPage { events: LimitAuditEvent[]; next_cursor: string | null }

/** Limit state of one provider under one auth mode. */
export interface ProviderAuthLimits {
  auth_mode: UsdAuthMode
  transport_available: boolean
  search: LimitRecord | null
  fetch: LimitRecord | null
  free_tiers: TierBalance[]
  paid_tiers: TierBalance[]
  unknown_tiers: TierBalance[]
  tier_split_known: boolean
  aggregate_pool: NativePool | null
  usd_views: UsdView[]
  rate_progress: RateProgressView[]
  grants: UsdGrantsSummary | null
  detail: ProviderLimitDetail | null
}

/** Dashboard payload for one provider: both auth modes and their views. */
export interface ProviderLimits {
  provider: string; active_auth_mode: UsdAuthMode; auths: ProviderAuthLimits[]
  documented_keyless_operations: string[]; version: number; generated_at: string
}

/** Outcome of one provider sync attempt. */
export interface ProviderLimitsSyncResult {
  provider: string; status: "synced" | "skipped" | "failed"; observed_at: string
  next_sync_at: string | null; error_code: string | null; stale: boolean; changed: boolean; reason: string | null
}

/** Partial catalog update. An omitted field keeps its value; null clears it. */
export interface ProviderLimitPatch {
  backendId: string; authMode: string; operation: UsdOperation; version: number
  rate?: LimitRate; budget?: LimitBudget; conversion_profile?: UsdConversionProfile
  plan_name?: string | null; usage_url?: string | null
}

export interface LimitHistoryQuery { backendId: string; authMode: string; limit?: number; cursor?: string | null }

/** One Free or Paid tier bar. Percentages stay null without an allowance. */
export interface TierBarView {
  tier: "free" | "paid"; poolIds: string[]; remainingUsd: string | null; allowanceUsd: string | null
  percentRemaining: number | null; source: string; confidence: UsdConfidence; resetNotes: string[]
  state: "finite" | "unmetered" | "postpaid" | "unknown"
}

/** One hour or day rate bar. `1s` and `1m` windows never reach this shape. */
export interface RateBarView {
  bucketId: string; operation: UsdOperation; window: UsdBarWindow; unit: UsdRateUnit; kind: UsdRateKind
  remaining: string | null; limit: string | null; resetAt: string | null
  percentRemaining: number | null; confidence: UsdConfidence
}

/** Input of one tier bar: the member balances of that tier only. */
export interface TierBarInput { tier: "free" | "paid"; balances: TierBalance[]; tierSplitKnown: boolean }

/** Input of one rate bar. */
export interface RateBarInput { progress: RateProgressView }
