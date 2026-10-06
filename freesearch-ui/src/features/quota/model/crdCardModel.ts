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
  CRDConfidence,
  CRDConversionProfile,
  CRDOperation,
  CRDState,
  CRDUsageTotal,
  CRDView,
  LimitRecord,
  ProviderAuthLimits,
  ProviderLimits,
} from "@/domains/dashboard"
import type { ProviderConfig } from "@/domains/providers"
import { formatCRDAmount, percentRemaining, sumAmounts } from "./crdDisplay"
import { multiplyDecimal, parseDecimal } from "./manualQuotaMath"

const OPERATIONS: readonly CRDOperation[] = ["search", "fetch"]
const USD_UNIT = "USD"
const FREE_UNIT = "FREE"
const UNKNOWN_TEXT = "unknown"
const MANUAL_ANCHOR_TEXT = "Estimated · Manual entry"
const USD_SCALE = 12
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
  usageTotals: CRDUsageTotal[]
}

/** Funds, USD valuation, priced use, and provenance of one provider card. */
export interface CreditCardModel {
  state: CRDState
  remainingCRD: string | null
  allowanceCRD: string | null
  percentRemaining: number | null
  remainingUSD: string | null
  pricedUseUSD: string | null
  provenanceNote: string | null
  poolIds: string[]
}

/** Input of the page price note. */
export interface PriceNoteInput {
  providers: ProviderConfig[]
  providerLimits: ProviderLimits[]
}

/** One supported operation price of one provider. */
export interface PriceNoteRow {
  provider: string
  providerName: string
  operation: CRDOperation
  usdPerCall: string
  crdPerCall: string
  priceVersion: string | null
  estimated: boolean
}

interface Funds {
  remainingCRD: string | null; allowanceCRD: string | null; remainingUSD: string | null; poolIds: string[]
}

const pow10 = (exp: number): bigint => 10n ** BigInt(exp)

function trimZeros(text: string): string {
  if (!text.includes(".")) return text
  const trimmed = text.replace(/0+$/, "").replace(/\.$/, "")
  return trimmed === "" ? "0" : trimmed
}

/** Exact quotient of two verbatim decimals, rounded half-up at `scale`. */
function divideDecimal(numerator: string, denominator: string, scale: number): string | null {
  const top = parseDecimal(numerator)
  const bottom = parseDecimal(denominator)
  if (!top || !bottom || bottom.int === 0n) return null
  const divisor = bottom.int * pow10(top.scale)
  const dividend = top.int * pow10(bottom.scale + scale)
  if (divisor === 0n) return null
  const quotient = dividend / divisor
  const remainder = dividend % divisor
  const rounded = remainder * 2n >= divisor ? quotient + 1n : quotient
  return rounded / pow10(scale) + "." + (rounded % pow10(scale)).toString().padStart(scale, "0")
}

function recordFor(auth: ProviderAuthLimits, operation: CRDOperation): LimitRecord | null {
  return operation === "search" ? auth.search : auth.fetch
}

/** An operation control exists only for a supported and reachable rail. */
export function operationAvailable(auth: ProviderAuthLimits, operation: CRDOperation): boolean {
  const record = recordFor(auth, operation)
  return record !== null && record.supported && record.transport_available
}

/** The active auth rail of one payload, with the current fallback to the first. */
export function activeAuth(limits: ProviderLimits): ProviderAuthLimits | undefined {
  return limits.auths.find((entry) => entry.auth_mode === limits.active_auth_mode) ?? limits.auths[0]
}

/** The profile of the first runnable rail, else the first reported rail. */
function applicableProfile(auth: ProviderAuthLimits): CRDConversionProfile | null {
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

function referenceProfile(profile: CRDConversionProfile | null): string | null {
  if (profile === null) return null
  const reference = parseDecimal(profile.reference_usd_per_crd)
  return reference === null || reference.int === 0n ? null : profile.reference_usd_per_crd
}

/** USD price of one native unit; USD is USD 1 and an unmetered unit is USD 0. */
function nativeUnitPrice(nativeUnit: string, profile: CRDConversionProfile): string | null {
  if (nativeUnit === USD_UNIT) return "1"
  if (nativeUnit === FREE_UNIT) return "0"
  return profile.native_usd_per_unit
}

function usdFromCRD(crd: string, profile: CRDConversionProfile | null): string | null {
  const reference = referenceProfile(profile)
  return reference === null ? null : multiplyDecimal(crd, reference)
}

function nativeToCRD(amount: string, nativeUnit: string, profile: CRDConversionProfile | null): string | null {
  const reference = referenceProfile(profile)
  const price = profile === null ? null : nativeUnitPrice(nativeUnit, profile)
  if (reference === null || price === null) return null
  const product = multiplyDecimal(amount, price)
  if (product === null) return null
  const value = divideDecimal(product, reference, USD_SCALE)
  return value === null ? null : trimZeros(value)
}

/** A native USD amount is USD directly; any other unit uses its source price. */
function nativeToUSD(amount: string, nativeUnit: string, profile: CRDConversionProfile | null): string | null {
  if (nativeUnit === USD_UNIT) return amount
  if (nativeUnit === FREE_UNIT || profile === null) return null
  const price = profile.native_usd_per_unit
  return price === null ? null : multiplyDecimal(amount, price)
}

/** The one aggregate vendor pool, when its balance is known. */
function poolFunds(auth: ProviderAuthLimits, profile: CRDConversionProfile | null): Funds | null {
  const pool = auth.aggregate_pool
  if (pool === null || pool.remaining === null) return null
  const remainingCRD = nativeToCRD(pool.remaining, pool.native_unit, profile)
  if (remainingCRD === null) return null
  const allowanceCRD =
    pool.allowance === null ? null : nativeToCRD(pool.allowance, pool.native_unit, profile)
  return {
    remainingCRD,
    allowanceCRD,
    remainingUSD: nativeToUSD(pool.remaining, pool.native_unit, profile),
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
function tierFunds(auth: ProviderAuthLimits, profile: CRDConversionProfile | null): Funds | null {
  const tiers = vendorTiers(auth)
  if (tiers.length === 0) return null
  const remainingCRD = sumAmounts(tiers.map((tier) => tier.remaining_crd))
  if (remainingCRD === null) return null
  return {
    remainingCRD,
    allowanceCRD: sumAmounts(tiers.map((tier) => tier.allowance_crd)),
    remainingUSD: usdFromCRD(remainingCRD, profile),
    poolIds: tiers.map((tier) => tier.pool_id),
  }
}

/** One funds row per distinct shared pool, so shared views add up once. */
function uniqueFiniteViews(views: CRDView[]): CRDView[] {
  const seen = new Set<string>()
  const kept: CRDView[] = []
  for (const view of views) {
    if (view.state !== "finite" || view.remaining_crd === null) continue
    const key = view.shared_pool_id ?? view.operation
    if (seen.has(key)) continue
    seen.add(key)
    kept.push(view)
  }
  return kept
}

/** One unique finite view shows its known funds without an invented allowance. */
function viewFunds(auth: ProviderAuthLimits, profile: CRDConversionProfile | null): Funds | null {
  const views = uniqueFiniteViews(auth.crd_views)
  if (views.length !== 1) return null
  const remaining = views[0].remaining_crd
  const poolId = views[0].shared_pool_id
  if (remaining === null) return null
  return {
    remainingCRD: remaining,
    allowanceCRD: null,
    remainingUSD: usdFromCRD(remaining, profile),
    poolIds: poolId === null ? [] : [poolId],
  }
}

function fallbackState(auth: ProviderAuthLimits): CRDState {
  const states = auth.crd_views.map((view) => view.state)
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

function sortableConfidence(value: string | null | undefined): CRDConfidence | null {
  if (value === null || value === undefined) return null
  const text = value.trim()
  if (text === "" || !(text in CONFIDENCE_RANK)) return null
  return text as CRDConfidence
}

/** The weakest known member confidence; an unknown member never strengthens it. */
function weakestConfidence(values: Array<string | null | undefined>): CRDConfidence | null {
  let result: CRDConfidence | null = null
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
  const parts = knownText([auth.aggregate_pool?.source, auth.detail?.source])
  const confidence = weakestConfidence([auth.aggregate_pool?.confidence, auth.detail?.confidence])
  if (confidence !== null) parts.push(confidence)
  if (stale) parts.push("stale")
  return parts.length === 0 ? null : parts.join(" · ")
}

/** Priced use in USD: the provider's exact CRD totals at the reference price. */
function pricedUse(usageTotals: CRDUsageTotal[], profile: CRDConversionProfile | null): string | null {
  if (usageTotals.length === 0) return null
  const total = sumAmounts(usageTotals.map((entry) => entry.normalized_crd))
  return total === null ? null : usdFromCRD(total, profile)
}

function modelOf(input: CreditCardInput, funds: Funds | null, profile: CRDConversionProfile | null): CreditCardModel {
  const shared = {
    pricedUseUSD: pricedUse(input.usageTotals, profile),
    provenanceNote: provenanceNote(input.auth),
  }
  if (funds === null) {
    return {
      ...shared,
      state: fallbackState(input.auth),
      remainingCRD: null,
      allowanceCRD: null,
      percentRemaining: null,
      remainingUSD: null,
      poolIds: [],
    }
  }
  return {
    ...shared,
    state: "finite",
    remainingCRD: funds.remainingCRD,
    allowanceCRD: funds.allowanceCRD,
    percentRemaining: percentRemaining(funds.remainingCRD, funds.allowanceCRD),
    remainingUSD: funds.remainingUSD,
    poolIds: funds.poolIds,
  }
}

/** Build the card model: one funds source, its USD value, and its priced use. */
export function creditCardModel(input: CreditCardInput): CreditCardModel {
  const profile = applicableProfile(input.auth)
  const funds = poolFunds(input.auth, profile) ?? tierFunds(input.auth, profile) ?? viewFunds(input.auth, profile)
  return modelOf(input, funds, profile)
}

function providerNameOf(providers: ProviderConfig[], providerId: string): string {
  return providers.find((provider) => provider.id === providerId)?.name ?? providerId
}

/**
 * Footer price rows: one row per supported operation of the reported payload.
 * The USD call value comes from `request_cost_crd` and its profile reference,
 * so an unknown or unsupported operation never becomes a price row.
 */
export function priceNoteRows(input: PriceNoteInput): PriceNoteRow[] {
  const rows: PriceNoteRow[] = []
  for (const limits of input.providerLimits) {
    const auth = activeAuth(limits)
    if (auth === undefined) continue
    for (const operation of OPERATIONS) {
      if (!operationAvailable(auth, operation)) continue
      const record = recordFor(auth, operation)
      const view = auth.crd_views.find((entry) => entry.operation === operation)
      if (record === null || view === undefined || view.request_cost_crd === null) continue
      const usdPerCall = usdFromCRD(view.request_cost_crd, record.conversion_profile)
      if (usdPerCall === null) continue
      const version = record.conversion_profile.price_version
      rows.push({
        provider: limits.provider,
        providerName: providerNameOf(input.providers, limits.provider),
        operation,
        usdPerCall,
        crdPerCall: formatCRDAmount(view.request_cost_crd),
        priceVersion: version === "" ? null : version,
        estimated: record.conversion_profile.estimated,
      })
    }
  }
  return rows
}
