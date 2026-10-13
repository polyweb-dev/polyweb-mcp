/**
 * Native Tavily Credits display model.
 *
 * One native Credit projects to 8 CRD at the PAYGO reference price (USD 0.008
 * per Credit, CRD reference USD 0.001), so every conversion is an exact
 * string-decimal step through the shared `parseDecimal`. CRD wire values stay
 * untouched: conversion happens only at this display boundary, and the profile
 * drives both directions. The display selects the aggregate native pool first
 * and falls back to native tiers and vendor detail; it never sums two
 * operation views of one pool.
 */

import type {
  CRDConversionProfile,
  CRDGrantsSummary,
  LimitRateWindow,
  NativePool,
  ProviderAuthLimits,
  TierBalance,
} from "@/domains/dashboard"
import { operationAvailable } from "./crdCardModel"
import { parseDecimal, subtractDecimal } from "./manualQuotaMath"

/** One balance state of a Tavily native rail; the unit stays `Credits` in all of them. */
type TavilyCreditsState = "finite" | "unknown" | "keyless" | "paygo" | "unavailable"

/** Display facts of one Tavily rail in native Credits. */
export interface TavilyCreditsDisplay {
  remaining: string | null
  allowance: string | null
  unit: "Credits"
  state: TavilyCreditsState
  source: string | null
  stale: boolean
  /** The local grant ceiling in unconverted CRD text; the label shows CRD. */
  localCap: string | null
  paygo: boolean
  resetAt: string | null
  /** The shared minute window as `remaining/limit` text; unknown stays null. */
  rateHeadroom: string | null
  retryAfterSeconds: number | null
}

/** The native display inputs of one Tavily rail, with its price profile. */
export interface TavilyDisplayAdapter {
  credits: TavilyCreditsDisplay
  /** The CRD conversion profile of the rail; null when the payload has none. */
  profile: CRDConversionProfile | null
}

/** The documented Tavily PAYGO price profile for views without a payload. */
export const DEFAULT_TAVILY_PROFILE: CRDConversionProfile = {
  reference_usd_per_crd: "0.001",
  native_usd_per_unit: "0.008",
  cost_basis: "paygo_reference",
  price_version: "paygo-reference",
  source: "documented",
  estimated: true,
}

const CREDIT_KIND = "CREDIT"
const OPERATOR_GRANT_SOURCE = "operator_grant"
const PAYGO_POOL_KEY = "paygo"
const MINUTE_WINDOW = "1m"
const UNKNOWN_WORDS = ["unknown", "n/a"]
const EXTRA_SCALE = 6
const OBSERVED_CONFIDENCE = new Set(["observed", "authoritative"])

interface Scaled {
  int: bigint
  scale: number
}

/** Known text only: an absent, empty, or unknown value yields null. */
function known(value: string | null | undefined): string | null {
  if (value === null || value === undefined) return null
  const text = value.trim()
  if (text === "" || UNKNOWN_WORDS.includes(text.toLowerCase())) return null
  return text
}

/** A CREDIT-kind unit text of any casing. */
function isCreditUnit(value: string | null | undefined): boolean {
  return (value ?? "").trim().toUpperCase() === CREDIT_KIND
}

/** A usable amount: any parseable non-negative decimal keeps its verbatim text. */
function usableAmount(value: string | null | undefined): string | null {
  const text = known(value)
  return text !== null && parseDecimal(text) !== null ? text : null
}

/** Exact common-scale integer of one parsed amount (target is never smaller). */
function alignTo(value: Scaled, scale: number): bigint {
  return value.int * 10n ** BigInt(scale - value.scale)
}

/** Trimmed decimal text of one scaled value. */
function formatScaled(value: bigint, scale: number): string {
  if (scale === 0) return value.toString()
  const divisor = 10n ** BigInt(scale)
  const fraction = (value % divisor).toString().padStart(scale, "0").replace(/0+$/, "")
  return fraction === "" ? (value / divisor).toString() : `${value / divisor}.${fraction}`
}

/**
 * `amount x (numerator / denominator)` at the shared extra scale, rounded
 * half-up. Divisors are always positive parsed prices, so no division by zero
 * reaches this step.
 */
function convertScaled(amount: Scaled, numerator: Scaled, denominator: Scaled): string {
  const target = amount.scale + EXTRA_SCALE
  const dividend = amount.int * numerator.int * 10n ** BigInt(numerator.scale + target)
  const divisor = denominator.int * 10n ** BigInt(denominator.scale + amount.scale)
  const quotient = dividend / divisor
  const rounded = (dividend % divisor) * 2n >= divisor ? quotient + 1n : quotient
  return formatScaled(rounded, target)
}

/** The parsed native price of one profile, or null when the profile is unknown. */
function profilePrices(profile: CRDConversionProfile): { perCredit: Scaled; perCRD: Scaled } | null {
  const perCredit = profile.native_usd_per_unit === null ? null : parseDecimal(profile.native_usd_per_unit)
  if (perCredit === null) return null
  const perCRD = profile.reference_usd_per_crd === null ? null : parseDecimal(profile.reference_usd_per_crd)
  if (perCRD === null || perCRD.int === 0n) return null
  return { perCredit, perCRD }
}

/**
 * Convert Credits to CRD: `credits x native_usd_per_unit / reference_usd_per_crd`.
 * Null when the profile or the price is unknown; the stored CRD stays untouched.
 */
export function tavilyCreditsToCRD(amount: string, profile: CRDConversionProfile): string | null {
  const prices = profilePrices(profile)
  const credits = parseDecimal(amount)
  if (prices === null || credits === null) return null
  return convertScaled(credits, prices.perCredit, prices.perCRD)
}

/**
 * Convert CRD to Credits: `crd x reference_usd_per_crd / native_usd_per_unit`.
 * Null when the profile is unknown or the native price is zero.
 */
export function tavilyCRDToCredits(amount: string, profile: CRDConversionProfile): string | null {
  const prices = profilePrices(profile)
  const crd = parseDecimal(amount)
  if (prices === null || crd === null || prices.perCredit.int === 0n) return null
  return convertScaled(crd, prices.perCRD, prices.perCredit)
}

/**
 * Visible number of one exact Credits amount: at most one decimal digit
 * (decimal ROUND_HALF_UP), no trailing ".0", "≈" when the shown value differs
 * from the exact one, "<0.1" below a tenth, "0" for zero, and null when the
 * text holds no decimal amount.
 */
export function formatCreditValue(amount: string): string | null {
  const value = parseDecimal(amount)
  if (value === null) return null
  if (value.int === 0n) return "0"
  const perTenth = 10n ** BigInt(value.scale)
  const numerator = value.int * 10n
  if (numerator < perTenth) return "<0.1"
  const whole = numerator / perTenth
  const remainder = numerator % perTenth
  const rounded = remainder * 2n >= perTenth ? whole + 1n : whole
  const exact = numerator === rounded * perTenth
  const wholeText = (rounded / 10n).toString()
  const numberText = rounded % 10n === 0n ? wholeText : `${wholeText}.${rounded % 10n}`
  return exact ? numberText : "≈" + numberText
}

/** Visible text of one exact Credits amount, always carrying its unit. */
export function formatCreditAmount(amount: string): string {
  const text = formatCreditValue(amount)
  if (text === null) return "Unknown Credits"
  return text === "1" ? "1 Credit" : text + " Credits"
}

interface NativeFunds {
  remaining: string | null
  allowance: string | null
  source: string | null
  resetAt: string | null
}

const EMPTY_FUNDS: NativeFunds = { remaining: null, allowance: null, source: null, resetAt: null }

/** Vendor funds only: an operator grant is a local ceiling, never vendor money. */
function vendorTiers(auth: ProviderAuthLimits): TierBalance[] {
  return [...auth.free_tiers, ...auth.paid_tiers].filter(
    (tier) => tier.tier !== "unknown" && tier.source !== OPERATOR_GRANT_SOURCE,
  )
}

/** Sum an operator grant to its exact unspent ceiling, or null when nothing is stored. */
function grantCeiling(grants: CRDGrantsSummary, operation: "search" | "fetch"): string | null {
  const granted = operation === "search" ? grants.search_granted_crd : grants.fetch_granted_crd
  const consumed = operation === "search" ? grants.search_consumed_crd : grants.fetch_consumed_crd
  const reserved = operation === "search" ? grants.search_reserved_crd : grants.fetch_reserved_crd
  if (granted === "0" && consumed === "0" && reserved === "0") return null
  const spent = subtractDecimal(granted, consumed)
  if (spent === null) return "0"
  const unreserved = subtractDecimal(spent, reserved)
  return unreserved === null ? "0" : unreserved
}

/** Compare two exact decimal strings: -1, 0, or 1. */
function compareDecimals(left: string, right: string): number {
  const first = parseDecimal(left)
  const second = parseDecimal(right)
  if (first === null || second === null) return 0
  const scale = Math.max(first.scale, second.scale)
  const leftInt = alignTo(first, scale)
  const rightInt = alignTo(second, scale)
  if (leftInt < rightInt) return -1
  return leftInt > rightInt ? 1 : 0
}

/**
 * The local grant ceiling of one rail in unconverted CRD text: the lower of
 * the stored search and fetch grant rest values. A missing ceiling stays null.
 */
function localCapOf(grants: CRDGrantsSummary | null): string | null {
  if (grants === null) return null
  const ceilings = ["search", "fetch"] as const
  let lowest: string | null = null
  for (const operation of ceilings) {
    const ceiling = grantCeiling(grants, operation)
    if (ceiling === null) continue
    lowest = lowest === null || compareDecimals(ceiling, lowest) < 0 ? ceiling : lowest
  }
  return lowest
}

/** The aggregate pool of one rail when it is a CREDIT-kind pool with values. */
function poolFunds(pool: NativePool | null): NativeFunds {
  if (pool === null || !isCreditUnit(pool.native_unit)) return EMPTY_FUNDS
  const remaining = usableAmount(pool.remaining)
  if (remaining === null) return EMPTY_FUNDS
  return {
    remaining,
    allowance: usableAmount(pool.allowance),
    source: known(pool.source),
    resetAt: pool.reset_at,
  }
}

/** The first vendor Credits tier with a known remaining amount, else its allowance. */
function tierFunds(tiers: TierBalance[]): NativeFunds {
  const credits = tiers.filter((tier) => isCreditUnit(tier.native_unit))
  for (const tier of credits) {
    const remaining = usableAmount(tier.native_remaining)
    if (remaining !== null) {
      return {
        remaining,
        allowance: usableAmount(tier.native_allowance),
        source: known(tier.source),
        resetAt: tier.reset_at,
      }
    }
  }
  for (const tier of credits) {
    const allowance = usableAmount(tier.native_allowance)
    if (allowance !== null) {
      return { remaining: null, allowance, source: known(tier.source), resetAt: tier.reset_at }
    }
  }
  return EMPTY_FUNDS
}

/** Native detail of one rail when it reports Credits values. */
function detailFunds(detail: ProviderAuthLimits["detail"]): NativeFunds {
  if (detail === null || !isCreditUnit(detail.native_unit)) return EMPTY_FUNDS
  return {
    remaining: usableAmount(detail.native_balance),
    allowance: usableAmount(detail.native_allowance),
    source: known(detail.source),
    resetAt: detail.reset_at,
  }
}

/** Vendor native funds of one rail: the aggregate pool first, then tiers, then detail. */
function fundsOf(auth: ProviderAuthLimits): NativeFunds {
  const pool = poolFunds(auth.aggregate_pool)
  if (pool.remaining !== null || pool.allowance !== null) return pool
  const tiers = tierFunds(vendorTiers(auth))
  if (tiers.remaining !== null || tiers.allowance !== null) return tiers
  const detail = detailFunds(auth.detail)
  if (detail.remaining !== null || detail.allowance !== null) return detail
  return EMPTY_FUNDS
}

/**
 * One state of a Tavily rail: keyless access, an unreachable keyed rail, the
 * observed PAYGO access, a known finite balance, or an unknown one.
 */
function stateOf(auth: ProviderAuthLimits, remaining: string | null): TavilyCreditsState {
  if (auth.auth_mode === "keyless") return "keyless"
  if (auth.auth_mode === "keyed" && !auth.transport_available) return "unavailable"
  const paygoTier = auth.paid_tiers.find(
    (tier) => tier.pool_id.toLowerCase().includes(PAYGO_POOL_KEY),
  )
  if (paygoTier !== undefined) {
    if (OBSERVED_CONFIDENCE.has(paygoTier.confidence)) return "paygo"
    const zero = remaining !== null && parseDecimal(remaining)?.int === 0n
    if (zero) return "paygo"
  }
  if (remaining !== null) return "finite"
  return "unknown"
}

/** Display facts of one Tavily rail: native Credits values with their sources. */
export function tavilyCredits(auth: ProviderAuthLimits): TavilyCreditsDisplay {
  const funds = fundsOf(auth)
  const state = stateOf(auth, funds.remaining)
  const listed = state === "keyless" || state === "unavailable"
  return {
    remaining: listed ? null : funds.remaining,
    allowance: listed ? null : funds.allowance,
    unit: "Credits",
    state,
    source: funds.source,
    stale: auth.aggregate_pool?.stale === true || auth.detail?.stale === true,
    localCap: localCapOf(auth.grants),
    paygo: state === "paygo",
    resetAt: funds.resetAt,
    rateHeadroom: minuteHeadroomOf(auth.detail === null ? [] : auth.detail.rate_windows),
    retryAfterSeconds: auth.detail?.retry_after_seconds ?? null,
  }
}

/** Visible shared minute headroom of one rail: "remaining/limit" minute text. */
export function minuteHeadroomOf(windows: LimitRateWindow[]): string | null {
  const minute = windows.find((entry) => entry.window === MINUTE_WINDOW)
  if (minute === undefined) return null
  const remaining = known(minute.remaining)
  if (remaining === null) return null
  const limit = known(minute.limit)
  return limit === null ? remaining : remaining + "/" + limit
}

/** The applicable CRD price profile of one rail: the runnable operation first. */
export function profileOf(auth: ProviderAuthLimits): CRDConversionProfile | null {
  const operations = ["search", "fetch"] as const
  for (const wantsAvailable of [true, false]) {
    for (const operation of operations) {
      if (wantsAvailable !== operationAvailable(auth, operation)) continue
      const record = operation === "search" ? auth.search : auth.fetch
      if (record !== null) return record.conversion_profile
    }
  }
  return null
}

/** Native display inputs of one Tavily rail; null for every other provider. */
export function displayAdapterOf(providerId: string, auth: ProviderAuthLimits): TavilyDisplayAdapter | null {
  if (providerId !== "tavily") return null
  return { credits: tavilyCredits(auth), profile: profileOf(auth) }
}
