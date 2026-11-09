/**
 * Field-level decoders for the provider limit wire contract.
 *
 * Every decoder accepts `unknown` and never throws: a missing optional stays
 * null, an unrecognized enum becomes "unknown", and an exact amount string
 * stays verbatim. Provider ids normalize to UI ids, like the other dashboard
 * mappers, so limit rows line up with the configured provider list.
 */

import { toUiId } from "@/domains/providers"
import type {
  UsdAuthMode,
  UsdBudgetModel,
  UsdConfidence,
  UsdConversionProfile,
  UsdExhaustAction,
  UsdFundingMode,
  UsdGrantsSummary,
  UsdNativeUnit,
  UsdOperation,
  UsdRateKind,
  UsdRateScope,
  UsdRateUnit,
  UsdRateWindow,
  UsdResetRule,
  UsdState,
  UsdTier,
  UsdUsageTotal,
  UsdView,
  LimitAuditEvent,
  LimitBudget,
  LimitRate,
  LimitRateWindow,
  LimitRecord,
  RateProgressView,
  TierBalance,
} from "../model/limitsTypes"

export type Raw = Record<string, unknown>

const STATES: readonly UsdState[] = ["finite", "unmetered", "unavailable", "unknown"]
const OPERATIONS: readonly UsdOperation[] = ["search", "fetch"]
export const AUTH_MODES: readonly UsdAuthMode[] = ["keyless", "keyed", "unknown"]
const CONFIDENCE: readonly UsdConfidence[] = ["authoritative", "observed", "estimated", "unknown"]
const RESET_RULES: readonly UsdResetRule[] = ["monthly_first", "vendor_period", "daily_vendor", "daily_estimate", "never", "unknown"]
const FUNDING_MODES: readonly UsdFundingMode[] = ["prepaid", "recurring", "postpaid", "no_budget", "unknown"]
const TIERS: readonly UsdTier[] = ["free", "paid", "unknown"]
const NATIVE_UNITS: readonly UsdNativeUnit[] = ["REQUEST", "CREDIT", "USD", "FREE", "unknown"]
const WINDOWS: readonly UsdRateWindow[] = ["1s", "1m", "1h", "1d", "unknown"]
const SCOPES: readonly UsdRateScope[] = ["org", "team", "key", "ip", "unknown"]
const RATE_UNITS: readonly UsdRateUnit[] = ["requests", "urls"]
const RATE_KINDS: readonly UsdRateKind[] = ["rate", "free_daily_allowance"]
const BUDGET_MODELS: readonly UsdBudgetModel[] = ["none", "requests", "credits", "usd", "unknown"]
const EXHAUST_ACTIONS: readonly UsdExhaustAction[] = ["402", "stop", "bill", "unknown"]

export function raw(value: unknown): Raw | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null
  return value as Raw
}

export const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : [])

export const text = (value: unknown): string => (typeof value === "string" ? value : "")

export function maybeText(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null
}

/** Keep an exact decimal amount verbatim; a JSON number keeps its own text. */
export function amount(value: unknown): string | null {
  if (typeof value === "string") return value.trim() === "" ? null : value
  if (typeof value === "number" && Number.isFinite(value)) return String(value)
  return null
}

export function count(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0
}

export function flag(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback
}

export function pick<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return typeof value === "string" && (allowed as readonly string[]).includes(value)
    ? (value as T)
    : fallback
}

export function operationOf(value: unknown): UsdOperation | null {
  return typeof value === "string" && (OPERATIONS as readonly string[]).includes(value)
    ? (value as UsdOperation)
    : null
}

export function mapItems<T>(value: unknown, decode: (item: unknown) => T | null): T[] {
  return list(value).map(decode).filter((item): item is T => item !== null)
}

export function decodeRateWindow(value: unknown): LimitRateWindow | null {
  const item = raw(value)
  if (!item) return null
  return {
    bucket_id: text(item.bucket_id),
    limit: amount(item.limit) ?? "",
    window: pick(item.window, WINDOWS, "unknown"),
    scope: pick(item.scope, SCOPES, "unknown"),
    unit: pick(item.unit, RATE_UNITS, "requests"),
    remaining: amount(item.remaining),
    reset_at: maybeText(item.reset_at),
    source: text(item.source),
    confidence: pick(item.confidence, CONFIDENCE, "unknown"),
  }
}

export function decodeRate(value: unknown): LimitRate | null {
  const item = raw(value)
  if (!item) return null
  return {
    windows: mapItems(item.windows, decodeRateWindow),
    published: flag(item.published, false),
  }
}

export function decodeBudget(value: unknown): LimitBudget | null {
  const item = raw(value)
  if (!item) return null
  return {
    model: pick(item.model, BUDGET_MODELS, "unknown"),
    free_allowance: amount(item.free_allowance),
    allowance_unit: text(item.allowance_unit),
    allowance_period: maybeText(item.allowance_period),
    cost_per_1k: amount(item.cost_per_1k),
    standard_native_cost: amount(item.standard_native_cost) ?? "",
    usd_per_call: amount(item.usd_per_call),
    on_exhausted: pick(item.on_exhausted, EXHAUST_ACTIONS, "unknown"),
    usage_api: maybeText(item.usage_api),
    priced: flag(item.priced, true),
  }
}

export function decodeConversion(value: unknown): UsdConversionProfile {
  const item = raw(value) ?? {}
  return {
    native_usd_per_unit: amount(item.native_usd_per_unit),
    cost_basis: text(item.cost_basis),
    price_version: text(item.price_version),
    source: text(item.source),
    estimated: flag(item.estimated, false),
  }
}

export function decodeRecord(value: unknown): LimitRecord | null {
  const item = raw(value)
  if (!item) return null
  const operation = operationOf(item.operation)
  if (operation === null) return null
  return {
    provider: toUiId(text(item.provider)),
    operation,
    auth_mode: text(item.auth_mode),
    supported: flag(item.supported, false),
    transport_available: flag(item.transport_available, false),
    rate: decodeRate(item.rate),
    budget: decodeBudget(item.budget),
    native_pool_id: maybeText(item.native_pool_id),
    conversion_profile: decodeConversion(item.conversion_profile),
    plan_name: maybeText(item.plan_name),
    usage_url: maybeText(item.usage_url),
    version: count(item.version),
  }
}

export function decodeUsdView(value: unknown): UsdView | null {
  const item = raw(value)
  if (!item) return null
  const operation = operationOf(item.operation)
  if (operation === null) return null
  return {
    state: pick(item.state, STATES, "unknown"),
    operation,
    remaining_usd: amount(item.remaining_usd),
    local_remaining_usd: amount(item.local_remaining_usd),
    request_cost_usd: amount(item.request_cost_usd),
    shared_pool_id: maybeText(item.shared_pool_id),
    possible_standard_calls: amount(item.possible_standard_calls),
    price_version: maybeText(item.price_version),
    priced: flag(item.priced, true),
  }
}

export function decodeTier(value: unknown): TierBalance | null {
  const item = raw(value)
  if (!item) return null
  const poolId = maybeText(item.pool_id)
  if (poolId === null) return null
  return {
    pool_id: poolId,
    tier: pick(item.tier, TIERS, "unknown"),
    native_unit: pick(item.native_unit, NATIVE_UNITS, "unknown"),
    native_remaining: amount(item.native_remaining),
    native_allowance: amount(item.native_allowance),
    remaining_usd: amount(item.remaining_usd),
    allowance_usd: amount(item.allowance_usd),
    reset_rule: pick(item.reset_rule, RESET_RULES, "unknown"),
    reset_at: maybeText(item.reset_at),
    funding_mode: pick(item.funding_mode, FUNDING_MODES, "unknown"),
    source: text(item.source),
    confidence: pick(item.confidence, CONFIDENCE, "unknown"),
    transport_available: flag(item.transport_available, false),
    label: maybeText(item.label),
  }
}

/** Only hour and day progress entries become bars; other windows are dropped. */
export function decodeRateProgress(value: unknown): RateProgressView | null {
  const item = raw(value)
  if (!item) return null
  const operation = operationOf(item.operation)
  if (operation === null) return null
  if (item.window !== "1h" && item.window !== "1d") return null
  return {
    bucket_id: text(item.bucket_id),
    operation,
    window: item.window,
    unit: pick(item.unit, RATE_UNITS, "requests"),
    remaining: amount(item.remaining),
    limit: amount(item.limit),
    reset_at: maybeText(item.reset_at),
    source: text(item.source),
    confidence: pick(item.confidence, CONFIDENCE, "unknown"),
    kind: pick(item.kind, RATE_KINDS, "rate"),
    stale: flag(item.stale, false),
    enforceable: flag(item.enforceable, false),
  }
}

export function decodeGrants(value: unknown): UsdGrantsSummary | null {
  const item = raw(value)
  if (!item) return null
  const zero = "0"
  return {
    provider: toUiId(text(item.provider)),
    auth_mode: text(item.auth_mode),
    period: pick(item.period, ["day", "week", "month"] as const, "month"),
    version: count(item.version),
    search_granted_usd: amount(item.search_granted_usd) ?? zero,
    search_consumed_usd: amount(item.search_consumed_usd) ?? zero,
    search_reserved_usd: amount(item.search_reserved_usd) ?? zero,
    fetch_granted_usd: amount(item.fetch_granted_usd) ?? zero,
    fetch_consumed_usd: amount(item.fetch_consumed_usd) ?? zero,
    fetch_reserved_usd: amount(item.fetch_reserved_usd) ?? zero,
  }
}

export function decodeEvent(value: unknown): LimitAuditEvent | null {
  const item = raw(value)
  if (!item) return null
  const eventId = maybeText(item.event_id)
  if (eventId === null) return null
  return {
    event_id: eventId,
    provider: toUiId(text(item.provider)),
    auth_mode: text(item.auth_mode),
    operation: maybeText(item.operation),
    pool_id: maybeText(item.pool_id),
    observed_at: text(item.observed_at),
    source: text(item.source),
    reason: text(item.reason),
    old_native: amount(item.old_native),
    new_native: amount(item.new_native),
    old_usd: amount(item.old_usd),
    new_usd: amount(item.new_usd),
    debit_usd: amount(item.debit_usd),
    native_debit: amount(item.native_debit),
    actual_usd: amount(item.actual_usd),
    confidence: pick(item.confidence, CONFIDENCE, "unknown"),
    local_attempt_id: maybeText(item.local_attempt_id),
    detail: raw(item.detail) ?? {},
  }
}

export function decodeUsageTotal(value: unknown): UsdUsageTotal | null {
  const item = raw(value)
  if (!item) return null
  const operation = operationOf(item.operation)
  if (operation === null) return null
  return {
    provider: toUiId(text(item.provider)),
    operation,
    spend_usd: amount(item.spend_usd) ?? "0",
    attempt_count: count(item.attempt_count),
    volume_count: count(item.volume_count),
  }
}
