/**
 * Facts of the card info popover.
 *
 * One card holds one popover. The popover states the call cost, the call count,
 * the rate limit, the last sync time, and the usage page of one rail. A fact
 * that no source reports stays absent, so the popover shows no placeholder.
 * Every amount stays an exact decimal string here; only the shown text rounds.
 */

import type { CRDResetRule, LimitRateWindow, NativePool, ProviderAuthLimits } from "@/domains/dashboard"
import { dollarText, formatCRDAmount } from "./crdDisplay"
import { operationAvailable, usdFromCRD } from "./crdCardModel"
import { operationLabel, type CreditMode } from "./quotaLabels"
import { timestampOrNull } from "./timeText"

/** One popover row: the fact label, its main value, and an optional quiet part. */
export interface ProviderInfoFact {
  label: string
  value: string
  note: string | null
}

/** Facts and usage link of one card info popover. */
export interface ProviderInfo {
  facts: ProviderInfoFact[]
  usageUrl: string | null
  /** The credit note of the popover header: the tier, the period, and the unit. */
  creditNote: string | null
  /** The credit tier of the rail; an absent tier yields null. */
  creditMode: CreditMode | null
  /** The funds source of the card subtitle; an absent source yields null. */
  statement: string | null
}

/** The observed native funds of one rail: the estimate start of a new entry. */
export interface BalancePrefill {
  allowance: string
  remaining: string
}

/**
 * The observed balance of one rail: the aggregate pool first, else the detail.
 *
 * Both amounts stay exact decimal strings. A rail without a known allowance or
 * a known remaining amount yields null, so no entry starts from a guess.
 */
export function balancePrefill(auth: ProviderAuthLimits): BalancePrefill | null {
  const allowance = known(auth.aggregate_pool?.allowance) ?? known(auth.detail?.native_allowance)
  const remaining = known(auth.aggregate_pool?.remaining) ?? known(auth.detail?.native_balance)
  if (allowance === null || remaining === null) return null
  return { allowance, remaining }
}

const OPERATIONS = ["search", "fetch"] as const
const UNKNOWN_TEXT = "unknown"

/** The reset rule gives the period of one call count. */
const COUNT_PERIOD: Record<CRDResetRule, string | null> = {
  monthly_first: "month",
  vendor_period: "vendor period",
  daily_vendor: "day",
  daily_estimate: "day",
  never: null,
  unknown: null,
}

/** The count row name of one operation. */
const COUNT_LABEL: Record<string, string> = { search: "Searches left", fetch: "Fetches left" }

/** Rate windows from tight to loose. Only the tightest known limit becomes a row. */
const RATE_WINDOW_ORDER = ["1s", "1m", "1h", "1d"]
const WINDOW_SHORT: Record<string, string> = { "1s": "sec", "1m": "min", "1h": "hour", "1d": "day" }
const RATE_UNIT_SHORT: Record<string, string> = { requests: "req", urls: "urls" }

/** A known text of one field; an absent, empty, or unknown value yields null. */
function known(value: string | null | undefined): string | null {
  if (value === null || value === undefined) return null
  const text = value.trim()
  if (text === "" || text.toLowerCase() === UNKNOWN_TEXT || text === "n/a") return null
  return text
}

/** Only http and https links become anchors; any other text yields null. */
export function safeHref(url: string | null | undefined): string | null {
  const text = known(url)
  return text !== null && /^https?:\/\//i.test(text) ? text : null
}

/** The tightest rate window with a known limit; no such window yields null. */
function rateWindowOf(windows: LimitRateWindow[]): LimitRateWindow | null {
  for (const window of RATE_WINDOW_ORDER) {
    const entry = windows.find((item) => item.window === window && known(item.limit) !== null)
    if (entry !== undefined) return entry
  }
  return null
}

function rateFact(windows: LimitRateWindow[]): ProviderInfoFact | null {
  const entry = rateWindowOf(windows)
  const limit = entry === null ? null : known(entry.limit)
  if (entry === null || limit === null) return null
  const unit = RATE_UNIT_SHORT[entry.unit] ?? entry.unit
  const window = WINDOW_SHORT[entry.window] ?? entry.window
  const scope = known(entry.scope)
  return {
    label: "Rate limit",
    value: limit + " " + unit + "/" + window,
    note: scope === null ? null : "(" + scope + ")",
  }
}

/** The CRD call cost of one available operation, with its USD value. */
function costFact(auth: ProviderAuthLimits, operation: (typeof OPERATIONS)[number]): ProviderInfoFact | null {
  const record = operation === "search" ? auth.search : auth.fetch
  const view = auth.crd_views.find((entry) => entry.operation === operation)
  const cost = known(view?.request_cost_crd)
  if (record === null || cost === null) return null
  const usd = usdFromCRD(cost, record.conversion_profile)
  return {
    label: operationLabel(operation) + " CRD cost",
    value: formatCRDAmount(cost),
    note: usd === null ? null : "(≈ " + dollarText(usd) + ")",
  }
}

/** The whole standard calls left of one operation, with the reset period. */
function countFact(auth: ProviderAuthLimits, operation: (typeof OPERATIONS)[number]): ProviderInfoFact | null {
  const view = auth.crd_views.find((entry) => entry.operation === operation)
  const calls = known(view?.possible_standard_calls)
  if (calls === null) return null
  const period = COUNT_PERIOD[auth.detail?.reset_rule ?? UNKNOWN_TEXT]
  return { label: COUNT_LABEL[operation], value: calls, note: period === null ? null : "/ " + period }
}

/** The card subtitle: the detail plan name, else the search record plan name. */
function planNameOf(auth: ProviderAuthLimits): string | null {
  return known(auth.detail?.plan_name) ?? known(auth.search?.plan_name)
}

/** One verb per confidence: it states how the funds became known. */
const SOURCE_VERB: Record<string, string> = {
  authoritative: "Reported by",
  estimated: "Estimated from",
  observed: "Observed from",
  unknown: "Recorded from",
}
const DEFAULT_VERB = "Recorded from"
/** The object of a balance that an operator entered by hand. */
const MANUAL_NOUN = "manually entered balance & calculated usage"
/** One object per funds source key. */
const SOURCE_NOUN: Record<string, string> = {
  documented: "the vendor price list",
  local: "local use",
  local_daily_estimate: "local use with a daily UTC reset",
  local_ledger: MANUAL_NOUN,
  manual_anchor: MANUAL_NOUN,
  operator: "the operator",
  operator_grant: "the operator budget limit",
  vendor_api: "the vendor API",
  vendor_headers: "the vendor API",
}

/** The object of the funds source; an absent or unknown source yields null. */
function sourceNoun(pool: NativePool | null): string | null {
  if (pool?.manual_anchor === true) return MANUAL_NOUN
  const source = known(pool?.source)
  return source === null ? null : (SOURCE_NOUN[source.toLowerCase()] ?? null)
}

/** The verb of the funds confidence. */
function sourceVerb(confidence: string | undefined): string {
  return SOURCE_VERB[(confidence ?? "").trim().toLowerCase()] ?? DEFAULT_VERB
}

/**
 * The card subtitle of one rail: the source of the funds as one sentence.
 *
 * A manual anchor states its estimate first. An absent or unknown source yields
 * null, so the card shows no invented source. A stale rail states that fact.
 */
function statementOf(auth: ProviderAuthLimits): string | null {
  const pool = auth.aggregate_pool
  const noun = sourceNoun(pool)
  if (noun === null) return null
  const statement = sourceVerb(pool?.confidence) + " " + noun
  return pool?.stale === true ? statement + " · stale" : statement
}

/** One word per allowance period. */
const PERIOD_WORD: Record<string, string> = {
  day: "Daily",
  daily: "Daily",
  month: "Monthly",
  monthly: "Monthly",
  week: "Weekly",
  weekly: "Weekly",
  year: "Yearly",
  yearly: "Yearly",
}
const CREDIT_UNIT_WORD = "Credits"

/** The credit tier of one rail: the free and paid facts of the payload. */
function creditModeOf(auth: ProviderAuthLimits): CreditMode | null {
  const free =
    auth.free_tiers.length > 0 ||
    known(auth.search?.budget?.free_allowance) !== null ||
    known(auth.fetch?.budget?.free_allowance) !== null
  const paid = auth.paid_tiers.length > 0
  if (free && paid) return "both"
  if (paid) return "paid"
  return free ? "free" : null
}

/** The period word of one rail: the allowance period, else the reset rule. */
function periodWordOf(auth: ProviderAuthLimits): string | null {
  const period = known(auth.search?.budget?.allowance_period) ?? known(auth.fetch?.budget?.allowance_period)
  if (period !== null) return PERIOD_WORD[period.toLowerCase()] ?? null
  const rule = auth.detail?.reset_rule
  if (rule === "monthly_first") return "Monthly"
  return rule === "daily_vendor" || rule === "daily_estimate" ? "Daily" : null
}

/**
 * The credit note of the popover header: the period and the credit unit.
 *
 * The note comes from the plan metadata of the payload: the allowance period
 * and the credit unit of the card. The note never states a tier word. A rail
 * without a period falls back to the reported plan name, so no note is invented.
 */
function creditNoteOf(auth: ProviderAuthLimits): string | null {
  const period = periodWordOf(auth)
  if (period === null) return planNameOf(auth)
  return [period, CREDIT_UNIT_WORD].join(" ")
}

/** Facts and usage link of one rail, in the shown order. */
export function providerInfo(auth: ProviderAuthLimits): ProviderInfo {
  const facts: ProviderInfoFact[] = []
  for (const operation of OPERATIONS) {
    if (!operationAvailable(auth, operation)) continue
    const cost = costFact(auth, operation)
    if (cost !== null) facts.push(cost)
    const count = countFact(auth, operation)
    if (count !== null) facts.push(count)
  }
  const rate = rateFact(auth.detail?.rate_windows ?? [])
  if (rate !== null) facts.push(rate)
  const lastSync = timestampOrNull(auth.detail?.last_sync_at)
  if (lastSync !== null) facts.push({ label: "Last sync", value: lastSync, note: null })
  return {
    facts,
    usageUrl: safeHref(auth.detail?.usage_url ?? null),
    creditNote: creditNoteOf(auth),
    creditMode: creditModeOf(auth),
    statement: statementOf(auth),
  }
}
