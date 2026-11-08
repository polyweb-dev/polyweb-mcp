/**
 * Facts of the card info popover.
 *
 * One card holds one popover. The popover states the call cost, the call count,
 * the rate limit, the last sync time, and the usage page of one rail. A fact
 * that no source reports stays absent, so the popover shows no placeholder.
 * Every amount stays an exact decimal string here; only the shown text rounds.
 */

import type { ProviderAuthLimits } from "@/domains/dashboard"
import { dollarText } from "./crdDisplay"
import { operationAvailable, usdFromCRD } from "./crdCardModel"
import { providerRateFacts } from "./providerRateFacts"
import { operationLabel, type CreditMode } from "./quotaLabels"
import { balanceStatement } from "./balanceStatement"
import { countFact } from "./providerInfoCounts"
import { nativeCostFact, tavilyRateFacts } from "./tavilyInfoFacts"

export type { ProviderInfo, ProviderInfoFact, BalancePrefill } from "./providerInfoTypes"
import type { ProviderInfo, ProviderInfoFact, BalancePrefill } from "./providerInfoTypes"
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

/** The provider id whose wire fetch operation reads as Extract. */
const TAVILY_ID = "tavily"

/** The shown operation name: Tavily names its wire fetch operation Extract. */
function operationViewName(providerId: string | undefined, operation: string): string {
  if (providerId === TAVILY_ID && operation === "fetch") return "Extract"
  return operationLabel(operation)
}

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

/** The provider's price for one operation, in dollars or as a free tier. */
function costFact(
  auth: ProviderAuthLimits,
  operation: (typeof OPERATIONS)[number],
  providerId: string | undefined,
): ProviderInfoFact | null {
  const record = operation === "search" ? auth.search : auth.fetch
  if (record === null) return null
  const label = operationViewName(providerId, operation) + " cost"
  if (["unbilled_free", "unbilled_keyless"].includes(record.conversion_profile.source)) {
    return { label, value: "Free", note: null }
  }
  const view = auth.crd_views.find((entry) => entry.operation === operation)
  const cost = known(view?.request_cost_crd)
  if (cost === null) return null
  const usd = usdFromCRD(cost, record.conversion_profile)
  return usd === null ? null : { label: label + " (USD)", value: dollarText(usd), note: null }
}

/** The card subtitle: the detail plan name, else the search record plan name. */
function planNameOf(auth: ProviderAuthLimits): string | null {
  return known(auth.detail?.plan_name) ?? known(auth.search?.plan_name)
}

/**
 * The card subtitle of one rail: the source of the funds as one sentence.
 *
 * A manual anchor states its estimate first. An absent or unknown source yields
 * null, so the card shows no invented source. A stale rail states that fact.
 */
function statementOf(auth: ProviderAuthLimits): string | null {
  return balanceStatement(auth.aggregate_pool)
    ?? (auth.rate_progress.some((entry) => entry.source === "local_attempts") ? "Locally counted usage" : null)
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
const CREDIT_UNIT_WORD = "credits"

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
 * A Tavily rail names Tavily Credits, with Monthly Tavily Credits for a monthly period.
 */
function creditNoteOf(auth: ProviderAuthLimits, providerId?: string): string | null {
  const period = periodWordOf(auth)
  if (period === null) return planNameOf(auth)
  const unit = providerId === TAVILY_ID ? "Tavily credits" : CREDIT_UNIT_WORD
  return [period, unit].join(" ")
}

/** One operation section: the cost and count facts of one available rail. */
function appendOperationFacts(
  facts: ProviderInfoFact[],
  auth: ProviderAuthLimits,
  operation: (typeof OPERATIONS)[number],
  options: { providerId: string | undefined; wholeRequests: boolean },
): void {
  const { providerId, wholeRequests } = options
  if (!operationAvailable(auth, operation)) return
  if (providerId === TAVILY_ID) {
    const native = nativeCostFact(auth, operation)
    if (native !== null) facts.push(native)
  }
  const cost = costFact(auth, operation, providerId)
  if (cost !== null) facts.push(cost)
  const count = countFact(auth, operation, providerId, wholeRequests)
  if (count !== null) facts.push(count)
}

/** Facts and usage link of one rail, in the shown order. */
export function providerInfo(
  auth: ProviderAuthLimits,
  providerId?: string,
  wholeRequests: boolean = false,
  rateLimitOverride?: string,
): ProviderInfo {
  const facts: ProviderInfoFact[] = []
  if (providerId === TAVILY_ID) {
    const operations = OPERATIONS.filter((operation) => operationAvailable(auth, operation))
    const factories = [
      (operation: "search" | "fetch") => nativeCostFact(auth, operation),
      (operation: "search" | "fetch") => countFact(auth, operation, providerId, wholeRequests),
      (operation: "search" | "fetch") => costFact(auth, operation, providerId),
    ]
    for (const factory of factories) {
      for (const operation of operations) {
        const fact = factory(operation)
        if (fact !== null) facts.push(fact)
      }
    }
    facts.push(...tavilyRateFacts(auth, rateLimitOverride))
  } else {
    for (const operation of OPERATIONS) {
      appendOperationFacts(facts, auth, operation, { providerId, wholeRequests })
    }
    facts.push(...providerRateFacts(auth, providerId, wholeRequests))
  }
  const lastSync = known(auth.detail?.last_sync_at)
  if (lastSync !== null) facts.push({ label: "Last sync", value: lastSync, note: null })
  return {
    facts,
    usageUrl: safeHref(auth.detail?.usage_url ?? null),
    creditNote: creditNoteOf(auth, providerId),
    creditMode: creditModeOf(auth),
    statement: statementOf(auth),
  }
}
