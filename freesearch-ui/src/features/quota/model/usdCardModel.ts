/**
 * Card-level credit-unit model.
 *
 * One provider card shows one funds bar. The vendor aggregate pool is the
 * preferred source; complete known vendor tiers come next, and one unique
 * finite credit-unit view comes last. A local grant ceiling and a vendor cash
 * value never replace vendor funds. Every amount stays an exact decimal
 * string; only the visible percentage becomes a number.
 */

import type {
  UsdConfidence,
  UsdConversionProfile,
  UsdOperation,
  UsdState,
  UsdUsageTotal,
  UsdView,
  LimitRecord,
  ProviderAuthLimits,
  ProviderLimits,
} from "@/domains/dashboard"
import { formatUsdAmount, percentRemaining, sumAmounts } from "./usdDisplay"
import { multiplyDecimal, parseDecimal } from "./manualQuotaMath"
import { buildPriceNoteRows, type PriceNoteInput, type PriceNoteRow } from "./priceNoteRows"
import { sourceLabel, BALANCE_ENTRY } from "./quotaLabels"

export type { PriceNoteInput, PriceNoteRow } from "./priceNoteRows"

const OPERATIONS: readonly UsdOperation[] = ["search", "fetch"]
const USD_UNIT = "USD"
const FREE_UNIT = "FREE"
const UNKNOWN_TEXT = "unknown"
const MANUAL_ANCHOR_TEXT = "Estimated · " + BALANCE_ENTRY
/** Confidence order: the weakest applicable member governs a combined note. */
const CONFIDENCE_RANK: Record<string, number> = {
  authoritative: 3,
  observed: 2,
  estimated: 1,
  unknown: 0,
}

/** Input of one card model: the active rail and this provider's use rows only. */
export interface CreditCardInput {
  auth: ProviderAuthLimits
  usageTotals: UsdUsageTotal[]
}

/** Funds, USD valuation, priced use, and provenance of one provider card. */
export interface CreditCardModel {
  state: UsdState
  remainingUsd: string | null
  allowanceUsd: string | null
  percentRemaining: number | null
  pricedUseUsd: string | null
  provenanceNote: string | null
  poolIds: string[]
}

interface Funds {
  remainingUsd: string | null; allowanceUsd: string | null; poolIds: string[]
}

function recordFor(auth: ProviderAuthLimits, operation: UsdOperation): LimitRecord | null {
  return operation === "search" ? auth.search : auth.fetch
}

/** An operation control exists only for a supported and reachable rail. */
export function operationAvailable(auth: ProviderAuthLimits, operation: UsdOperation): boolean {
  const record = recordFor(auth, operation)
  return record !== null && record.supported && record.transport_available
}

/** Select the active credential rail reported by this provider limits payload. */
export function activeAuth(limits: ProviderLimits): ProviderAuthLimits | undefined {
  return limits.auths.find((entry) => entry.auth_mode === limits.active_auth_mode) ?? limits.auths[0]
}

/** The profile of the first runnable rail, else the first reported rail. */
function applicableProfile(auth: ProviderAuthLimits): UsdConversionProfile | null {
  for (const wanted of [true, false]) {
    for (const operation of OPERATIONS) {
      if (!wanted && operationAvailable(auth, operation)) continue
      if (wanted && !operationAvailable(auth, operation)) continue
      const record = recordFor(auth, operation)
      if (record !== null) return record.conversion_profile
    }
  }
  return null
}

function nativeToUsd(amount: string, nativeUnit: string, profile: UsdConversionProfile | null): string | null {
  if (nativeUnit === USD_UNIT) return parseDecimal(amount) === null ? null : amount
  if (nativeUnit === FREE_UNIT) return "0"
  const price = profile?.native_usd_per_unit
  return price == null ? null : multiplyDecimal(amount, price)
}

/** The one aggregate vendor pool, when its balance is known. */
function poolFunds(auth: ProviderAuthLimits, profile: UsdConversionProfile | null): Funds | null {
  const pool = auth.aggregate_pool
  if (pool === null || pool.remaining === null) return null
  const remainingUsd = nativeToUsd(pool.remaining, pool.native_unit, profile)
  if (remainingUsd === null) return null
  const allowanceUsd =
    pool.allowance === null ? null : nativeToUsd(pool.allowance, pool.native_unit, profile)
  return {
    remainingUsd,
    allowanceUsd,

    poolIds: [pool.pool_id],
  }
}

/** Vendor tiers only: one row per distinct pool, and never an operator grant. */
function vendorTiers(auth: ProviderAuthLimits) {
  const seen = new Set<string>()
  const tiers = []
  for (const tier of [...auth.free_tiers, ...auth.paid_tiers]) {
    if (tier.tier === "unknown" || tier.source === "operator_grant" || seen.has(tier.pool_id)) {
      continue
    }
    seen.add(tier.pool_id)
    tiers.push(tier)
  }
  return tiers
}

/** Complete known vendor tiers of distinct pools; a partial set stays unknown. */
function tierFunds(auth: ProviderAuthLimits): Funds | null {
  const tiers = vendorTiers(auth)
  if (tiers.length === 0) return null
  const remainingUsd = sumAmounts(tiers.map((tier) => tier.remaining_usd))
  if (remainingUsd === null) return null
  return {
    remainingUsd,
    allowanceUsd: sumAmounts(tiers.map((tier) => tier.allowance_usd)),

    poolIds: tiers.map((tier) => tier.pool_id),
  }
}

/** One funds row per distinct shared pool, so shared views add up once. */
function uniqueFiniteViews(views: UsdView[]): UsdView[] {
  const seen = new Set<string>()
  const kept: UsdView[] = []
  for (const view of views) {
    if (view.state !== "finite" || view.remaining_usd === null) continue
    const key = view.shared_pool_id ?? view.operation
    if (seen.has(key)) continue
    seen.add(key)
    kept.push(view)
  }
  return kept
}

/** One unique finite view shows its known funds without an invented allowance. */
function viewFunds(auth: ProviderAuthLimits): Funds | null {
  const views = uniqueFiniteViews(auth.usd_views)
  if (views.length !== 1) return null
  const remaining = views[0].remaining_usd
  const poolId = views[0].shared_pool_id
  if (remaining === null) return null
  return {
    remainingUsd: remaining,
    allowanceUsd: null,

    poolIds: poolId === null ? [] : [poolId],
  }
}

function fallbackState(auth: ProviderAuthLimits): UsdState {
  const states = auth.usd_views.map((view) => view.state)
  if (states.includes("unmetered")) return "unmetered"
  if (states.length > 0 && states.every((state) => state === "unavailable")) return "unavailable"
  return "unknown"
}

function knownText(values: Array<string | null | undefined>): string[] {
  const kept: string[] = []
  for (const value of values) {
    if (value === null || value === undefined || value === "" || value === UNKNOWN_TEXT) continue
    if (!kept.includes(value)) kept.push(value)
  }
  return kept
}

function sortableConfidence(value: string | null | undefined): UsdConfidence | null {
  if (value === null || value === undefined) return null
  const text = value.trim()
  if (text === "" || !(text in CONFIDENCE_RANK)) return null
  return text as UsdConfidence
}

/** The weakest known member confidence; an unknown member never strengthens it. */
function weakestConfidence(values: Array<string | null | undefined>): UsdConfidence | null {
  let result: UsdConfidence | null = null
  for (const value of values) {
    const candidate = sortableConfidence(value)
    if (candidate === null) continue
    if (result === null || CONFIDENCE_RANK[candidate] < CONFIDENCE_RANK[result]) result = candidate
  }
  return result
}

function isStale(auth: ProviderAuthLimits): boolean {
  return (auth.aggregate_pool?.stale ?? false) || (auth.detail?.stale ?? false)
}

/** One compact provenance note: the weakest applicable confidence and a stale flag. */
function provenanceNote(auth: ProviderAuthLimits): string | null {
  const stale = isStale(auth)
  if (auth.aggregate_pool?.manual_anchor === true) {
    return stale ? MANUAL_ANCHOR_TEXT + " · stale" : MANUAL_ANCHOR_TEXT
  }
  const parts = knownText([
    sourceLabel(auth.aggregate_pool?.source),
    sourceLabel(auth.detail?.source),
  ])
  const confidence = weakestConfidence([auth.aggregate_pool?.confidence, auth.detail?.confidence])
  if (confidence !== null) parts.push(confidence)
  if (stale) parts.push("stale")
  return parts.length === 0 ? null : parts.join(" · ")
}

/** Priced use in USD: the provider's exact Usd totals at the reference price. */
function pricedUse(usageTotals: UsdUsageTotal[]): string | null {
  if (usageTotals.length === 0) return null
  const total = sumAmounts(usageTotals.map((entry) => entry.spend_usd))
  return total === null ? null : total
}

function modelOf(input: CreditCardInput, funds: Funds | null): CreditCardModel {
  const shared = {
    pricedUseUsd: pricedUse(input.usageTotals),
    provenanceNote: provenanceNote(input.auth),
  }
  if (funds === null) {
    return {
      ...shared,
      state: fallbackState(input.auth),
      remainingUsd: null,
      allowanceUsd: null,
      percentRemaining: null,

      poolIds: [],
    }
  }
  return {
    ...shared,
    state: "finite",
    remainingUsd: funds.remainingUsd,
    allowanceUsd: funds.allowanceUsd,
    percentRemaining: percentRemaining(funds.remainingUsd, funds.allowanceUsd),

    poolIds: funds.poolIds,
  }
}

/** Build the card model: one funds source, its USD value, and its priced use. */
export function creditCardModel(input: CreditCardInput): CreditCardModel {
  const profile = applicableProfile(input.auth)
  const funds = poolFunds(input.auth, profile) ?? tierFunds(input.auth) ?? viewFunds(input.auth)
  return modelOf(input, funds)
}

/** Footer price rows from runtime limits and documented provider references. */
export function priceNoteRows(input: PriceNoteInput): PriceNoteRow[] {
  return buildPriceNoteRows(input, { activeAuth, formatUsdAmount })
}
