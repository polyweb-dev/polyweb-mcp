/**
 * Public decoders for the provider limit wire contract.
 *
 * Each entry point accepts `unknown` and never throws: a single limit
 * response, a dashboard array, or an absent field all decode to a safe empty
 * list. Exact amount strings stay verbatim; provider ids normalize to UI ids.
 */

import { toUiId } from "@/domains/providers"
import {
  AUTH_MODES,
  amount,
  count,
  decodeUsdView,
  decodeEvent,
  decodeGrants,
  decodeRateWindow,
  decodeRateProgress,
  decodeRecord,
  decodeTier,
  decodeUsageTotal,
  flag,
  list,
  mapItems,
  maybeText,
  pick,
  raw,
  text,
} from "./limitsWireFields"
import type {
  UsdUsageTotal,
  LimitHistoryPage,
  NativePool,
  ProviderAuthLimits,
  ProviderLimitDetail,
  ProviderLimits,
} from "../model/limitsTypes"

const RESET_RULES = ["monthly_first", "vendor_period", "daily_vendor", "daily_estimate", "never", "unknown"] as const
const CONFIDENCE = ["authoritative", "observed", "estimated", "unknown"] as const

/** Whole-second Retry-After delay from unknown data; a negative stays null and zero stays zero. */
function retryAfterSeconds(value: unknown): number | null {
  if (typeof value === "number") {
    return Number.isFinite(value) && value >= 0 ? value : null
  }
  if (typeof value === "string") {
    const text = value.trim()
    if (text === "") return null
    const parsed = Number(text)
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : null
  }
  return null
}

export function decodePool(value: unknown): NativePool | null {
  const item = raw(value)
  if (!item) return null
  const poolId = maybeText(item.pool_id)
  if (poolId === null) return null
  return {
    pool_id: poolId,
    provider: toUiId(text(item.provider)),
    auth_mode: text(item.auth_mode),
    native_unit: text(item.native_unit),
    remaining: amount(item.remaining),
    allowance: amount(item.allowance),
    actual_spend_usd: amount(item.actual_spend_usd),
    source: text(item.source),
    confidence: text(item.confidence) || "unknown",
    reset_at: maybeText(item.reset_at),
    observed_at: maybeText(item.observed_at),
    version: count(item.version),
    credential_generation: count(item.credential_generation),
    next_sync_at: maybeText(item.next_sync_at),
    stale: flag(item.stale, false),
    manual_anchor: flag(item.manual_anchor, false),
  }
}

export function decodeDetail(value: unknown): ProviderLimitDetail | null {
  const item = raw(value)
  if (!item) return null
  return {
    plan_name: maybeText(item.plan_name),
    native_unit: maybeText(item.native_unit),
    native_balance: amount(item.native_balance),
    native_allowance: amount(item.native_allowance),
    usd_per_call: amount(item.usd_per_call),
    actual_spend_usd: amount(item.actual_spend_usd),
    reset_at: maybeText(item.reset_at),
    reset_rule: pick(item.reset_rule, RESET_RULES, "unknown"),
    usage_url: maybeText(item.usage_url),
    source: text(item.source),
    confidence: pick(item.confidence, CONFIDENCE, "unknown"),
    last_sync_at: maybeText(item.last_sync_at),
    stale: flag(item.stale, false),
    price_version: text(item.price_version),
    balance_split_note: maybeText(item.balance_split_note),
    rate_windows: mapItems(item.rate_windows, decodeRateWindow),
    retry_after_seconds: retryAfterSeconds(item.retry_after_seconds),
    tier_split_known: flag(item.tier_split_known, true),
    aggregate_pool_id: maybeText(item.aggregate_pool_id),
  }
}

function decodeAuth(value: unknown): ProviderAuthLimits | null {
  const item = raw(value)
  if (!item) return null
  return {
    auth_mode: pick(item.auth_mode, AUTH_MODES, "unknown"),
    transport_available: flag(item.transport_available, false),
    search: decodeRecord(item.search),
    fetch: decodeRecord(item.fetch),
    free_tiers: mapItems(item.free_tiers, decodeTier),
    paid_tiers: mapItems(item.paid_tiers, decodeTier),
    unknown_tiers: mapItems(item.unknown_tiers, decodeTier),
    tier_split_known: flag(item.tier_split_known, true),
    aggregate_pool: decodePool(item.aggregate_pool),
    usd_views: mapItems(item.usd_views, decodeUsdView),
    rate_progress: mapItems(item.rate_progress, decodeRateProgress),
    grants: decodeGrants(item.grants),
    detail: decodeDetail(item.detail),
  }
}

function decodeProvider(value: unknown): ProviderLimits | null {
  const item = raw(value)
  if (!item) return null
  const provider = maybeText(item.provider)
  if (provider === null) return null
  return {
    provider: toUiId(provider),
    active_auth_mode: pick(item.active_auth_mode, AUTH_MODES, "unknown"),
    auths: mapItems(item.auths, decodeAuth),
    documented_keyless_operations: list(item.documented_keyless_operations).filter(
      (entry): entry is string => typeof entry === "string",
    ),
    version: count(item.version),
    generated_at: text(item.generated_at),
  }
}

/** Decode one limit response, a dashboard array, or a dashboard field. */
export function decodeProviderLimits(value: unknown): ProviderLimits[] {
  if (Array.isArray(value)) return mapItems(value, decodeProvider)
  const item = raw(value)
  if (!item) return []
  if (Array.isArray(item.provider_limits)) return mapItems(item.provider_limits, decodeProvider)
  const single = decodeProvider(item)
  return single === null ? [] : [single]
}

export function decodeLimitHistory(value: unknown): LimitHistoryPage {
  const item = raw(value)
  if (!item) return { events: [], next_cursor: null }
  return { events: mapItems(item.events, decodeEvent), next_cursor: maybeText(item.next_cursor) }
}

/** Accept the bare array or the dashboard field that wraps it. */
export function decodeUsdUsageTotals(value: unknown): UsdUsageTotal[] {
  const item = raw(value)
  if (item !== null && Array.isArray(item.spend_totals)) {
    return mapItems(item.spend_totals, decodeUsageTotal)
  }
  return mapItems(value, decodeUsageTotal)
}
