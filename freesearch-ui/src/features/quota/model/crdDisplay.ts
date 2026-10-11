/**
 * Credit-unit (CRD) display and card model. Exact decimal strings stay exact in the model; only the visible text is rounded, with decimal
 * ROUND_HALF_UP on the digit that is shown. One CRD is USD 0.001 of priced native use. Never render a positive balance as zero.
 */

import type {
  CRDConfidence,
  CRDResetRule,
  CRDState,
  CRDView,
  LimitRecord,
  ProviderAuthLimits,
  RateBarInput,
  RateBarView,
  TierBalance,
  TierBarInput,
  TierBarView,
} from "@/domains/dashboard"
import { parseDecimal } from "./manualQuotaMath"

const UNMETERED_TEXT = "Free - unmetered"
const UNAVAILABLE_TEXT = "n/a"
const UNKNOWN_TEXT = "Unknown"

const CONFIDENCE_RANK: Record<CRDConfidence, number> = { authoritative: 3, observed: 2, estimated: 1, unknown: 0 }
const RESET_TEXT: Record<CRDResetRule, string> = {
  monthly_first: "Resets on the first of the month",
  vendor_period: "Resets on the vendor period",
  daily_vendor: "Resets each day (vendor)",
  daily_estimate: "Resets each day (UTC estimate)",
  never: "Never resets",
  unknown: "Reset rule unknown",
}

interface Scaled { int: bigint; scale: number }
/** Parse one exact non-negative decimal string, or null when it is not one. */
const scaled = (amount: string): Scaled | null => parseDecimal(amount)

/** Scale a parsed amount to a common number of decimal places. */
const align = (value: Scaled, scale: number): bigint => value.int * 10n ** BigInt(scale - value.scale)

/** Compare two exact decimal strings: -1, 0, or 1. */
function compareDecimals(left: string, right: string): number {
  const a = scaled(left)
  const b = scaled(right)
  if (a === null || b === null) return 0
  const scale = Math.max(a.scale, b.scale)
  const leftInt = align(a, scale)
  const rightInt = align(b, scale)
  if (leftInt < rightInt) return -1
  return leftInt > rightInt ? 1 : 0
}

/** The smallest exact amount of the list; null when the list is empty. */
function minAmount(values: string[]): string | null {
  return values.reduce<string | null>(
    (lowest, value) => (lowest === null || compareDecimals(value, lowest) < 0 ? value : lowest),
    null,
  )
}

/** Exact spendable capacity of one view: the lower of the projectable native funds and the local grant ceiling, so a ceiling is never hidden. */
function spendableCRD(view: CRDView): string | null {
  const values = [view.remaining_crd, view.local_remaining_crd].filter((value): value is string => value !== null)
  return minAmount(values)
}

/**
 * Format one exact CRD amount for display: at most one decimal digit, decimal ROUND_HALF_UP, no trailing ".0", "≈" when the visible amount
 * differs from the exact amount, "<0.1 CRD" for a positive amount below 0.1, and exactly "0 CRD" for zero. A string that is not a plain
 * decimal amount becomes "Unknown", never a number.
 */
export function formatCRDAmount(amount: string): string {
  const value = scaled(amount)
  if (value === null) return UNKNOWN_TEXT
  if (value.int === 0n) return "0 CRD"
  // Tenths of a CRD, rounded half-up: rounded = round(amount * 10).
  const perTenth = 10n ** BigInt(value.scale)
  const numerator = value.int * 10n
  if (numerator < perTenth) return "<0.1 CRD"
  const whole = numerator / perTenth
  const remainder = numerator % perTenth
  const rounded = remainder * 2n >= perTenth ? whole + 1n : whole
  const exact = value.int * 10n === rounded * perTenth
  const wholeText = (rounded / 10n).toString()
  const numberText = rounded % 10n === 0n ? wholeText : `${wholeText}.${rounded % 10n}`
  return `${exact ? "" : "≈"}${numberText} CRD`
}

/** Dollar form of one exact USD amount for display: "4.500" becomes "$4.5", and "5.000" becomes "$5". */
export function dollarText(amount: string): string {
  const text = amount.trim()
  const trimmed = text.includes(".") ? text.replace(/0+$/, "").replace(/\.$/, "") : text
  return "$" + (trimmed === "" ? "0" : trimmed)
}

/** Visible text of one credit-unit view, including its non-finite states. */
export function formatCRD(view: CRDView): string {
  if (view.state === "unmetered") return UNMETERED_TEXT
  if (view.state === "unavailable") return UNAVAILABLE_TEXT
  if (view.state === "unknown") return UNKNOWN_TEXT
  const amount = spendableCRD(view)
  return amount === null ? UNKNOWN_TEXT : formatCRDAmount(amount)
}

function stateText(state: CRDState): string {
  if (state === "unmetered") return UNMETERED_TEXT
  if (state === "unavailable") return UNAVAILABLE_TEXT
  return UNKNOWN_TEXT
}

/** Whole standard calls, floored; null when the count is absent. */
export function callsText(amount: string | null): string | null {
  const value = amount === null ? null : scaled(amount)
  return value === null ? null : (value.int / 10n ** BigInt(value.scale)).toString()
}

/** An unsupported rail is unavailable; a missing record stays unknown. A finite view without a spendable amount is unknown, never zero. */
function operationState(view: CRDView | null, record: LimitRecord | null): CRDState {
  if (view === null) {
    if (record === null) return "unknown"
    return record.supported && record.transport_available ? "unknown" : "unavailable"
  }
  if (view.state === "finite" && spendableCRD(view) === null) return "unknown"
  return view.state
}

/** One operation headline plus its honest state. */
function operationView(
  auth: ProviderAuthLimits,
  operation: "search" | "fetch",
): { view: CRDView | null; state: CRDState; headline: string } {
  const view = auth.crd_views.find((entry) => entry.operation === operation) ?? null
  const record = operation === "search" ? auth.search : auth.fetch
  const state = operationState(view, record)
  return { view, state, headline: view === null ? stateText(state) : formatCRD(view) }
}

function overallState(search: CRDState, fetch: CRDState): CRDState {
  const states = [search, fetch]
  if (states.every((state) => state === "unavailable")) return "unavailable"
  if (states.includes("finite")) return "finite"
  if (states.includes("unmetered")) return "unmetered"
  if (states.includes("unknown")) return "unknown"
  return "unavailable"
}

/** Input of one provider card model. */
export interface ProviderCRDInput { provider: string; providerName: string; authMode: string; auth: ProviderAuthLimits }

/** Card model: search and fetch headlines, states, and honest notes. */
export interface ProviderCRDModel {
  provider: string; providerName: string; authMode: string; state: CRDState; searchState: CRDState; fetchState: CRDState
  searchHeadline: string; fetchHeadline: string; sharedPoolId: string | null; sharedNote: string | null; notes: string[]
}

function callsNotes(search: CRDView | null, fetch: CRDView | null): string[] {
  const notes: string[] = []
  const searchCalls = callsText(search === null ? null : search.possible_standard_calls)
  if (searchCalls !== null) notes.push(`About ${searchCalls} standard search calls remain`)
  const fetchCalls = callsText(fetch === null ? null : fetch.possible_standard_calls)
  if (fetchCalls !== null) notes.push(`About ${fetchCalls} standard fetch calls remain`)
  return notes
}

function lowestCeiling(views: Array<CRDView | null>): string | null {
  const ceilings: string[] = []
  for (const view of views) {
    if (view !== null && view.local_remaining_crd !== null) ceilings.push(view.local_remaining_crd)
  }
  return minAmount(ceilings)
}

function sharedPoolId(views: Array<CRDView | null>): string | null {
  const searchPool = views[0]?.shared_pool_id ?? null
  const fetchPool = views[1]?.shared_pool_id ?? null
  return searchPool !== null && searchPool === fetchPool ? searchPool : null
}

/** Build the card model. Shared views read one fund source, so the model reports the shared pool once and states that headlines do not add up. */
export function providerCRDModel(input: ProviderCRDInput): ProviderCRDModel {
  const { auth } = input
  const search = operationView(auth, "search")
  const fetch = operationView(auth, "fetch")
  const views = [search.view, fetch.view]
  const notes = callsNotes(search.view, fetch.view)
  const ceiling = lowestCeiling(views)
  if (ceiling !== null) notes.push(`Local grant ceiling ${formatCRDAmount(ceiling)}`)
  if (views.some((view) => view !== null && !view.priced)) {
    notes.push("Priced use is not configured; the CRD value stays unknown")
  }
  const poolId = sharedPoolId(views)
  const sharedNote = poolId === null ? null : `Shared pool ${poolId}: the two views read the same funds and do not add up.`
  return {
    provider: input.provider, providerName: input.providerName, authMode: input.authMode,
    state: overallState(search.state, fetch.state), searchState: search.state, fetchState: fetch.state,
    searchHeadline: search.headline, fetchHeadline: fetch.headline,
    sharedPoolId: poolId, sharedNote, notes,
  }
}

/** Sum exact amounts; null when any member amount is unknown. */
export function sumAmounts(values: Array<string | null>): string | null {
  if (values.length === 0) return null
  let scale = 0
  const parsed: Scaled[] = []
  for (const value of values) {
    if (value === null) return null
    const item = scaled(value)
    if (item === null) return null
    parsed.push(item)
    scale = Math.max(scale, item.scale)
  }
  const total = parsed.reduce((sum, item) => sum + align(item, scale), 0n)
  if (scale === 0) return total.toString()
  const divisor = 10n ** BigInt(scale)
  return `${total / divisor}.${(total % divisor).toString().padStart(scale, "0")}`
}

/** Remaining percentage, rounded half-up to one digit; null without a known positive base (never the remaining amount itself). */
export function percentRemaining(remaining: string | null, allowance: string | null): number | null {
  if (remaining === null || allowance === null) return null
  const numerator = scaled(remaining)
  const denominator = scaled(allowance)
  if (numerator === null || denominator === null) return null
  const scale = Math.max(numerator.scale, denominator.scale)
  const top = align(numerator, scale) * 1000n
  const bottom = align(denominator, scale)
  if (bottom <= 0n) return null
  const quotient = top / bottom
  const rest = top % bottom
  const tenths = rest * 2n >= bottom ? quotient + 1n : quotient
  const clamped = tenths < 0n ? 0n : tenths > 1000n ? 1000n : tenths
  return Number(clamped) / 10
}

/** Text of one reset rule, with the visible reset date when it is known. */
export function resetRuleText(rule: CRDResetRule, resetAt: string | null): string {
  const base = RESET_TEXT[rule]
  if (resetAt === null) return base
  const date = new Date(resetAt)
  if (Number.isNaN(date.getTime())) return `${base} (${resetAt})`
  return `${base} (${date.toLocaleDateString(undefined, { month: "short", day: "numeric" })})`
}

const uniqueNotes = (values: string[]): string[] => values.filter((value, index) => values.indexOf(value) === index)
const resetNote = (balance: TierBalance): string => resetRuleText(balance.reset_rule, balance.reset_at)

/** A combined bar carries the weakest member confidence; combining a strong and a weak member cannot claim the strong one. */
function weakestConfidence(balances: TierBalance[]): CRDConfidence {
  return balances.reduce<CRDConfidence>(
    (weakest, balance) => (CONFIDENCE_RANK[balance.confidence] < CONFIDENCE_RANK[weakest] ? balance.confidence : weakest),
    "authoritative",
  )
}

function tierState(balances: TierBalance[]): TierBarView["state"] {
  if (balances.every((balance) => balance.remaining_crd !== null)) return "finite"
  if (balances.every((balance) => balance.funding_mode === "postpaid")) return "postpaid"
  if (balances.every((balance) => balance.funding_mode === "no_budget")) return "unmetered"
  return "unknown"
}

function emptyTierBar(input: TierBarInput, notes: string[]): TierBarView {
  return {
    tier: input.tier, poolIds: [], remainingCRD: null, allowanceCRD: null, percentRemaining: null,
    source: "unknown", confidence: "unknown", resetNotes: notes, state: "unknown",
  }
}

/**
 * Build one Free or Paid tier bar. Several subpools of one tier combine only when every member amount is known, and each different reset rule
 * keeps its own note. An unknown tier split stays unknown with a "Tier split unavailable" note, so no division of aggregate funds is invented.
 */
export function tierBarModel(input: TierBarInput): TierBarView {
  if (!input.tierSplitKnown) return emptyTierBar(input, ["Tier split unavailable"])
  if (input.balances.length === 0) return emptyTierBar(input, [])
  const balances = input.balances
  const remainingCRD = sumAmounts(balances.map((balance) => balance.remaining_crd))
  const allowanceCRD = sumAmounts(balances.map((balance) => balance.allowance_crd))
  return {
    tier: input.tier,
    poolIds: uniqueNotes(balances.map((balance) => balance.pool_id)),
    remainingCRD,
    allowanceCRD,
    percentRemaining: percentRemaining(remainingCRD, allowanceCRD),
    source: uniqueNotes(balances.map((balance) => balance.source).filter(Boolean)).join(", ") || "unknown",
    confidence: weakestConfidence(balances),
    resetNotes: uniqueNotes(balances.map(resetNote)),
    state: tierState(balances),
  }
}

/**
 * Build one hour or day rate bar. The backend reports `1h` and `1d` windows in its rate progress list, so second and minute windows stay detail
 * text. A percentage appears only with a known positive limit, so an unknown limit is never drawn as empty capacity.
 */
export function rateBarModel(input: RateBarInput): RateBarView {
  const progress = input.progress
  return {
    bucketId: progress.bucket_id, operation: progress.operation, window: progress.window,
    unit: progress.unit, kind: progress.kind, remaining: progress.remaining, limit: progress.limit,
    resetAt: progress.reset_at, percentRemaining: percentRemaining(progress.remaining, progress.limit),
    confidence: progress.confidence,
  }
}
